"""FastAPI 웹 서버 — 단일 슬롯 연수원 예약 봇."""

from __future__ import annotations

import asyncio
import json
import logging
from collections import deque
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse

import config
import facilities
import notifier
from checker import date_range
from scheduler import BookingResult, MonitorScheduler

logger = logging.getLogger(__name__)

TEMPLATES_DIR = Path(__file__).parent / "templates"
INDEX_HTML = TEMPLATES_DIR / "index.html"

LOG_BUFFER_MAX = 200
PASSWORD_MASK = "********"


class AppState:
    """앱 전역 상태 — 단일 슬롯."""

    def __init__(self) -> None:
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


state = AppState()


class WebSocketLogHandler(logging.Handler):
    """logging.Handler — 로그를 log_buffer에 저장하고 WS로 브로드캐스트."""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            ts = datetime.fromtimestamp(record.created).strftime("%H:%M:%S")
            msg = self.format(record)
            line = f"{ts} [{record.levelname}] {msg}"
            entry = state.append_log(line)
            state._broadcast(entry)
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
    state.loop = asyncio.get_running_loop()
    _install_log_handler()
    logger.info("YeonsuBot 웹 서버 시작")
    try:
        yield
    finally:
        logger.info("YeonsuBot 웹 서버 종료 중...")
        state.scheduler.stop()
        # 워커 스레드 join (최대 15초)
        worker = state.scheduler._worker
        if worker and worker.is_alive():
            worker.join(timeout=15)


app = FastAPI(lifespan=lifespan, title="YeonsuBot")


# ── helpers ──

def _mask_password(settings: dict) -> dict:
    out = dict(settings)
    if out.get("password"):
        out["password"] = PASSWORD_MASK
    return out


def _status_payload() -> dict:
    running = state.scheduler.is_running
    next_check_at: str | None = None
    if running and state.last_check_at:
        try:
            last_dt = datetime.strptime(state.last_check_at, "%H:%M:%S")
            next_dt = last_dt + timedelta(seconds=state.scheduler._interval)
            next_check_at = next_dt.strftime("%H:%M:%S")
        except Exception:
            next_check_at = None

    settings = config.load()
    target = None
    if settings.get("facility") and settings.get("checkin") and settings.get("checkout"):
        target = f"{settings['facility']} {settings['checkin']}~{settings['checkout']}"

    return {
        "running": running,
        "status": state.current_status,
        "last_check_at": state.last_check_at,
        "next_check_at": next_check_at,
        "target": target,
        "last_result": state.last_result,
    }


# ── REST 엔드포인트 ──

@app.get("/", response_class=HTMLResponse)
async def index() -> HTMLResponse:
    if not INDEX_HTML.exists():
        return HTMLResponse("<h1>templates/index.html 을 찾을 수 없습니다.</h1>", status_code=500)
    return HTMLResponse(INDEX_HTML.read_text(encoding="utf-8"))


@app.get("/api/status")
async def api_status() -> JSONResponse:
    return JSONResponse(_status_payload())


@app.get("/api/settings")
async def api_get_settings() -> JSONResponse:
    settings = config.load()
    # 저장된 비밀번호는 Base64 인코딩됨 — 마스킹만 하고 실제 값은 내보내지 않음
    return JSONResponse({
        **_mask_password(settings),
        "facilities": facilities.get_facility_names(),
    })


@app.post("/api/start")
async def api_start(request: Request) -> JSONResponse:
    if state.scheduler.is_running:
        raise HTTPException(status_code=409, detail="이미 실행 중입니다.")

    body = await request.json()
    username = (body.get("username") or "").strip()
    password = body.get("password") or ""
    facility_name = (body.get("facility") or "").strip()
    checkin = (body.get("checkin") or "").strip()
    checkout = (body.get("checkout") or "").strip()
    interval_seconds = int(body.get("interval_seconds") or 60)

    # 검증
    if not username:
        raise HTTPException(status_code=400, detail="아이디를 입력하세요.")
    if not password:
        # 비밀번호가 빈 값이거나 마스크면 기존 저장값 복원
        existing = config.load()
        if not existing.get("password"):
            raise HTTPException(status_code=400, detail="비밀번호를 입력하세요.")
        password_encoded = existing["password"]
        password_plain = config.decode_password(password_encoded)
    elif password == PASSWORD_MASK:
        existing = config.load()
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
    config.save({
        "username": username,
        "password": password_encoded,
        "facility": facility_name,
        "checkin": checkin,
        "checkout": checkout,
        "interval_seconds": interval_seconds,
    })

    state.last_result = None
    state.last_check_at = None
    state.scheduler.start(
        interval_seconds=interval_seconds,
        yeonsu_gbn=facility_code,
        target_dates=target_dates,
        username=username,
        password=password_plain,
    )
    return JSONResponse(_status_payload())


@app.post("/api/stop")
async def api_stop() -> JSONResponse:
    state.scheduler.stop()
    state.current_status = "중지"
    return JSONResponse(_status_payload())


@app.post("/api/slack/test")
async def api_slack_test() -> JSONResponse:
    ok = notifier.send_test_notification(notifier.SLACK_WEBHOOK_URL)
    if not ok:
        raise HTTPException(status_code=502, detail="Slack 전송 실패")
    return JSONResponse({"ok": True})


@app.post("/api/logs/clear")
async def api_logs_clear() -> JSONResponse:
    state.log_buffer.clear()
    await state._async_broadcast({"type": "clear"})
    return JSONResponse({"ok": True})


# ── WebSocket ──

@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket) -> None:
    await ws.accept()
    state.ws_clients.add(ws)
    try:
        # 연결 직후 버퍼된 로그 즉시 전송
        for entry in list(state.log_buffer):
            await ws.send_json(entry)
        # 현재 상태도 한 번 전송
        await ws.send_json({
            "type": "status",
            "status": state.current_status,
            "last_check_at": state.last_check_at,
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
        state.ws_clients.discard(ws)
