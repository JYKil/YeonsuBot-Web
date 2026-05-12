"""FastAPI 웹 서버 — 단일 슬롯 연수원 예약 봇."""

from __future__ import annotations

import asyncio
import logging
import threading
from collections import deque
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone

_KST = timezone(timedelta(hours=9))
from pathlib import Path

from fastapi import Cookie, Depends, FastAPI, HTTPException, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse

import auth
import config
import facilities
import notifier
from checker import BrowserSession, LoginError, date_range
from log_context import USER_CTX
from scheduler import BookingResult, MonitorScheduler

logger = logging.getLogger(__name__)

TEMPLATES_DIR = Path(__file__).parent / "templates"
INDEX_HTML = TEMPLATES_DIR / "index.html"

LOG_BUFFER_MAX = 200
PASSWORD_MASK = "********"


class SessionContext:
    """사용자 1명분 스케줄러/로그/WebSocket 상태."""

    def __init__(self, username: str) -> None:
        self.username = username
        self.scheduler: MonitorScheduler = MonitorScheduler()
        self.ws_clients: set[WebSocket] = set()
        self.log_buffer: deque[dict] = deque(maxlen=LOG_BUFFER_MAX)
        self.current_status: str = "중지"
        self.last_check_at: str | None = None
        self.last_result: dict | None = None  # {"result": "SUCCESS"|"FAILED"|..., "detail": ...}
        self.loop: asyncio.AbstractEventLoop | None = None

        # scheduler 콜백 연결
        self.scheduler.on_status_change = self._on_status_change
        self.scheduler.on_booking_result = self._on_booking_result
        self.scheduler.on_error = self._on_error
        self.scheduler.on_check_result = self._on_check_result
        self.scheduler.on_cycle_start = self._on_cycle_start

    # ── scheduler 콜백 (워커 스레드에서 호출됨) ──

    def _on_status_change(self, status: str) -> None:
        self.current_status = status
        self._broadcast({"type": "status", "status": status, "last_check_at": self.last_check_at})

    def _on_booking_result(self, result: BookingResult, detail: str) -> None:
        payload = {"result": result.name, "detail": detail}
        self.last_result = payload
        self._broadcast({"type": "result", **payload})

    def _on_error(self, error: Exception) -> None:
        self._broadcast({"type": "error", "message": str(error)})

    def _on_check_result(self, available: list | None, facility_code: str) -> None:
        self.last_check_at = datetime.now().strftime("%H:%M:%S")
        self._broadcast({"type": "status", "status": self.current_status, "last_check_at": self.last_check_at})

    def _on_cycle_start(self, cycle: int) -> None:
        # 2번째 사이클부터 로그에 시각적 구분자 삽입
        if cycle > 1:
            entry = {"type": "log", "message": "", "separator": True}
            self.log_buffer.append(entry)
            self._broadcast(entry)

    # ── WebSocket 브로드캐스트 ──

    def append_log(self, message: str) -> dict:
        entry = {"type": "log", "message": message}
        self.log_buffer.append(entry)
        return entry

    def _broadcast(self, message: dict) -> None:
        """워커 스레드에서 asyncio 루프로 안전하게 전달."""
        if self.loop is None or self.loop.is_closed():
            return
        asyncio.run_coroutine_threadsafe(self._async_broadcast(message), self.loop)

    async def _async_broadcast(self, message: dict) -> None:
        if not self.ws_clients:
            return
        dead: list[WebSocket] = []
        for ws in list(self.ws_clients):
            try:
                await ws.send_json(message)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.ws_clients.discard(ws)


class SchedulerRegistry:
    """사용자별 SessionContext 레지스트리."""

    def __init__(self, max_concurrent: int = 3) -> None:
        self._contexts: dict[str, SessionContext] = {}
        self._lock = threading.Lock()
        self._max_concurrent = max_concurrent
        self.loop: asyncio.AbstractEventLoop | None = None

    def get_or_create(self, username: str) -> SessionContext:
        with self._lock:
            ctx = self._contexts.get(username)
            if ctx:
                return ctx

            running_count = sum(1 for context in self._contexts.values() if context.scheduler.is_running)
            if running_count >= self._max_concurrent:
                raise HTTPException(status_code=503, detail=f"동시 실행 한도({self._max_concurrent})에 도달했습니다.")

            ctx = SessionContext(username)
            ctx.loop = self.loop
            self._contexts[username] = ctx
            return ctx

    def get(self, username: str) -> SessionContext | None:
        with self._lock:
            return self._contexts.get(username)

    def drop(self, username: str) -> None:
        with self._lock:
            ctx = self._contexts.pop(username, None)
        if ctx:
            ctx.scheduler.stop()

    def set_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        with self._lock:
            self.loop = loop
            for ctx in self._contexts.values():
                ctx.loop = loop

    def contexts(self) -> list[SessionContext]:
        with self._lock:
            return list(self._contexts.values())


registry = SchedulerRegistry()


class WebSocketLogHandler(logging.Handler):
    """logging.Handler — 로그를 log_buffer에 저장하고 WS로 브로드캐스트."""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            username = USER_CTX.get(None)
            if not username:
                return
            ctx = registry.get(username)
            if not ctx:
                return

            ts = datetime.fromtimestamp(record.created, tz=_KST).strftime("%H:%M:%S")
            msg = self.format(record)
            line = f"{ts} [{record.levelname}] {msg}"
            entry = ctx.append_log(line)
            ctx._broadcast(entry)
        except Exception:
            self.handleError(record)


def _install_log_handler() -> None:
    """루트 로거에 WS 핸들러 1회 등록."""
    root = logging.getLogger()
    if any(isinstance(h, WebSocketLogHandler) for h in root.handlers):
        return
    handler = WebSocketLogHandler()
    handler.setFormatter(logging.Formatter("%(name)s: %(message)s"))
    handler.setLevel(logging.INFO)
    root.addHandler(handler)
    if root.level > logging.INFO or root.level == logging.NOTSET:
        root.setLevel(logging.INFO)


@asynccontextmanager
async def lifespan(app: FastAPI):
    registry.set_loop(asyncio.get_running_loop())
    _install_log_handler()
    logger.info("YeonsuBot 웹 서버 시작")
    try:
        yield
    finally:
        logger.info("YeonsuBot 웹 서버 종료 중...")
        for ctx in registry.contexts():
            ctx.scheduler.stop()
            # 워커 스레드 join (최대 15초)
            worker = ctx.scheduler._worker
            if worker and worker.is_alive():
                worker.join(timeout=15)


app = FastAPI(lifespan=lifespan, title="YeonsuBot")


def _verify_login(username: str, password: str) -> None:
    session = BrowserSession()
    try:
        session.start(username, password)
    finally:
        session.stop()


# ── helpers ──

def _mask_password(settings: dict) -> dict:
    out = dict(settings)
    if out.get("password"):
        out["password"] = PASSWORD_MASK
    return out


def _status_payload(ctx: SessionContext) -> dict:
    running = ctx.scheduler.is_running
    next_check_at: str | None = None
    if running and ctx.last_check_at:
        try:
            last_dt = datetime.strptime(ctx.last_check_at, "%H:%M:%S")
            next_dt = last_dt + timedelta(seconds=ctx.scheduler._interval)
            next_check_at = next_dt.strftime("%H:%M:%S")
        except Exception:
            next_check_at = None

    settings = config.load(ctx.username)
    target = None
    if settings.get("facility") and settings.get("checkin") and settings.get("checkout"):
        target = f"{settings['facility']} {settings['checkin']}~{settings['checkout']}"

    return {
        "running": running,
        "status": ctx.current_status,
        "last_check_at": ctx.last_check_at,
        "next_check_at": next_check_at,
        "target": target,
        "last_result": ctx.last_result,
    }


# ── REST 엔드포인트 ──

@app.get("/", response_class=HTMLResponse)
async def index() -> HTMLResponse:
    if not INDEX_HTML.exists():
        return HTMLResponse("<h1>templates/index.html 을 찾을 수 없습니다.</h1>", status_code=500)
    return HTMLResponse(INDEX_HTML.read_text(encoding="utf-8"))


@app.get("/api/status")
async def api_status(user: str = Depends(auth.current_user)) -> JSONResponse:
    ctx = registry.get_or_create(user)
    return JSONResponse(_status_payload(ctx))


@app.post("/api/auth/login")
async def api_auth_login(request: Request) -> JSONResponse:
    body = await request.json()
    username = (body.get("username") or "").strip()
    password = body.get("password") or ""

    if not username or not password:
        raise HTTPException(status_code=400, detail="아이디와 비밀번호를 입력하세요.")

    try:
        settings = config.load(username)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="아이디 형식이 올바르지 않습니다.") from exc

    try:
        await asyncio.to_thread(_verify_login, username, password)
    except LoginError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    except Exception as exc:
        logger.warning("로그인 검증 실패: %s", exc)
        raise HTTPException(status_code=401, detail="로그인 검증에 실패했습니다.") from exc

    settings.update({
        "username": username,
        "password": config.encode_password(password),
    })
    config.save(username, settings)

    session_id = auth.create_session(username)
    response = JSONResponse({"ok": True, "username": username, "session_id": session_id})
    response.set_cookie(
        key=auth.SESSION_COOKIE_NAME,
        value=session_id,
        max_age=int(auth.SESSION_TTL.total_seconds()),
        httponly=True,
        samesite="lax",
    )
    return response


@app.post("/api/auth/logout")
async def api_auth_logout(request: Request) -> JSONResponse:
    # 헤더 우선, 없으면 쿠키 fallback
    session_id = request.headers.get("X-YeonsuBot-Session") or request.cookies.get(auth.SESSION_COOKIE_NAME)
    if session_id:
        username = auth.resolve_session(session_id)
        if username:
            registry.drop(username)
        auth.destroy_session(session_id)
    response = JSONResponse({"ok": True})
    response.delete_cookie(key=auth.SESSION_COOKIE_NAME)
    return response


@app.get("/api/auth/me")
async def api_auth_me(request: Request) -> JSONResponse:
    session_id = request.headers.get("X-YeonsuBot-Session") or request.cookies.get(auth.SESSION_COOKIE_NAME)
    username = auth.resolve_session(session_id)
    if not username:
        raise HTTPException(status_code=401, detail="인증이 필요합니다.")
    return JSONResponse({"username": username})


@app.get("/api/settings")
async def api_get_settings(user: str = Depends(auth.current_user)) -> JSONResponse:
    settings = config.load(user)
    # 저장된 비밀번호는 Base64 인코딩됨 — 마스킹만 하고 실제 값은 내보내지 않음
    return JSONResponse({
        **_mask_password(settings),
        "facilities": facilities.get_facility_names(),
    })


@app.post("/api/start")
async def api_start(request: Request, user: str = Depends(auth.current_user)) -> JSONResponse:
    ctx = registry.get_or_create(user)
    if ctx.scheduler.is_running:
        raise HTTPException(status_code=409, detail="이미 실행 중입니다.")

    body = await request.json()
    body_username = (body.get("username") or "").strip()
    password = body.get("password") or ""
    facility_name = (body.get("facility") or "").strip()
    checkin = (body.get("checkin") or "").strip()
    checkout = (body.get("checkout") or "").strip()
    interval_seconds = int(body.get("interval_seconds") or 60)
    username = user

    # 검증
    if body_username and body_username != user:
        raise HTTPException(status_code=400, detail="로그인 사용자와 요청 아이디가 다릅니다.")
    if not password:
        # 비밀번호가 빈 값이거나 마스크면 기존 저장값 복원
        existing = config.load(user)
        if not existing.get("password"):
            raise HTTPException(status_code=400, detail="비밀번호를 입력하세요.")
        password_encoded = existing["password"]
        password_plain = config.decode_password(password_encoded)
    elif password == PASSWORD_MASK:
        existing = config.load(user)
        password_encoded = existing.get("password", "")
        password_plain = config.decode_password(password_encoded)
        if not password_plain:
            raise HTTPException(status_code=400, detail="비밀번호를 입력하세요.")
    else:
        password_plain = password
        password_encoded = config.encode_password(password)

    facility_code = facilities.get_facility_code(facility_name)
    if not facility_code:
        raise HTTPException(status_code=400, detail=f"알 수 없는 연수원: {facility_name}")
    if not checkin or not checkout:
        raise HTTPException(status_code=400, detail="체크인/체크아웃 날짜를 입력하세요.")

    # 대상 날짜 = [checkin, checkout) — 마지막 체크아웃일은 포함 안 함
    try:
        last_dt = datetime.strptime(checkout, "%Y-%m-%d") - timedelta(days=1)
        target_dates = date_range(checkin, last_dt.strftime("%Y-%m-%d"))
    except ValueError:
        raise HTTPException(status_code=400, detail="날짜 형식이 올바르지 않습니다 (YYYY-MM-DD).")
    if not target_dates:
        raise HTTPException(status_code=400, detail="날짜 범위가 비어있습니다.")

    # 설정 저장 (비밀번호는 인코딩 상태로)
    config.save(user, {
        "username": username,
        "password": password_encoded,
        "facility": facility_name,
        "checkin": checkin,
        "checkout": checkout,
        "interval_seconds": interval_seconds,
    })

    ctx.last_result = None
    ctx.last_check_at = None

    # 새 세션 시작 — 기존 로그 초기화
    ctx.log_buffer.clear()
    await ctx._async_broadcast({"type": "clear"})

    ctx.scheduler.start(
        interval_seconds=interval_seconds,
        yeonsu_gbn=facility_code,
        target_dates=target_dates,
        username=username,
        password=password_plain,
        log_username=ctx.username,
    )
    return JSONResponse(_status_payload(ctx))


@app.post("/api/stop")
async def api_stop(user: str = Depends(auth.current_user)) -> JSONResponse:
    ctx = registry.get_or_create(user)
    ctx.scheduler.stop()
    ctx.current_status = "중지"
    return JSONResponse(_status_payload(ctx))


@app.post("/api/slack/test")
async def api_slack_test(user: str = Depends(auth.current_user)) -> JSONResponse:
    settings = config.load(user)
    webhook_url = settings.get("slack_webhook_url") or notifier.SLACK_WEBHOOK_URL
    ok = await asyncio.to_thread(notifier.send_test_notification, webhook_url)
    if not ok:
        raise HTTPException(status_code=502, detail="Slack 테스트 전송에 실패했습니다.")
    return JSONResponse({"ok": True})


@app.post("/api/logs/clear")
async def api_logs_clear(user: str = Depends(auth.current_user)) -> JSONResponse:
    ctx = registry.get_or_create(user)
    ctx.log_buffer.clear()
    await ctx._async_broadcast({"type": "clear"})
    return JSONResponse({"ok": True})


# ── WebSocket ──

@app.websocket("/ws")
async def ws_endpoint(
    ws: WebSocket,
    session_id: str | None = Query(None),
) -> None:
    username = auth.resolve_session(session_id)
    if not username:
        await ws.accept()
        await ws.close(code=4401, reason="authentication required")
        return

    await ws.accept()
    ctx = registry.get_or_create(username)
    ctx.ws_clients.add(ws)
    try:
        # 연결 직후 버퍼된 로그 즉시 전송
        for entry in list(ctx.log_buffer):
            await ws.send_json(entry)
        # 현재 상태도 한 번 전송
        await ws.send_json({
            "type": "status",
            "status": ctx.current_status,
            "last_check_at": ctx.last_check_at,
        })
        # 클라이언트 메시지 대기 (ping 용)
        while True:
            try:
                await ws.receive_text()
            except WebSocketDisconnect:
                break
    except WebSocketDisconnect:
        pass
    except Exception as exc:
        logger.warning("WS 오류: %s", exc)
    finally:
        ctx.ws_clients.discard(ws)
