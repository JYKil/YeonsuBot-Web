# YeonsuBot-Web 멀티 계정 동시 실행 전환 계획

> 목적: 현재 "단일 슬롯"(한 번에 한 계정만 모니터링) 구조를 **여러 사용자가 동시에 각자 봇을 돌릴 수 있는** 구조로 전환한다.
>
> 작업 도구: (CLI)
> 작업 방식: 각 Phase 단위로 커밋. Phase 사이에는 반드시 수동 검증 후 다음으로 넘어간다.

---

## 0. 작업 전 준비

### 0.1 컨텍스트 확인 (시작 시 첫 명령)

```
Read MULTI_USER_PLAN.md, AGENTS.md, plan.md, web_server.py, scheduler.py, config.py, checker.py 전체.
이 계획서를 따라 작업할 거야. Phase별로 진행하고, 각 Phase 끝나면 변경 요약 + 다음 Phase 진입 여부를 나에게 물어봐.
```

### 0.2 브랜치 분리

```bash
git checkout -b feature/multi-user
```

### 0.3 백업 확인

- `data/settings.json`이 운영 중인 단일 사용자 설정을 담고 있다.
- Phase 2에서 마이그레이션 스크립트로 `data/users/<username>/settings.json`으로 옮긴다.
- 마이그레이션 전에 `data/settings.json.backup`을 만들어 둘 것.

---

## 1. 현재 구조 요약 (수정 대상)

| 파일 | 단일성을 만드는 지점 |
|---|---|
| `web_server.py` | 전역 싱글톤 `AppState`(scheduler 1개, log_buffer 1개, ws_clients 1개, current_status/last_check_at/last_result 1개) |
| `scheduler.py` | `MonitorScheduler` 인스턴스가 `AppState`에 1개만 존재. 클래스 자체는 인스턴스화 가능 — 다중화 가능. |
| `config.py` | `data/settings.json` 단일 파일. `load()` / `save(settings)`가 인자에 username 없음. |
| `templates/index.html` | 로그인 UI 없음. WebSocket이 모든 클라이언트에 같은 메시지 브로드캐스트. |
| 접근 제어 | 없음 (README에 명시) |

### 핵심 전환 원칙

1. `username`을 **모든 상태의 키**로 사용한다.
2. `AppState` 1개 → `SessionContext`(사용자 1명분) × N개를 담는 `SchedulerRegistry`로 분리한다.
3. WebSocket 브로드캐스트는 **해당 사용자의 클라이언트들에게만** 가야 한다. (다른 사용자가 내 로그를 보면 사고)
4. 인증은 "연수원 사이트 자격 그대로" 사용. 별도 회원 DB 없음.
5. 동시 실행 슬롯 수에 **상한**을 둔다. (브라우저 1개당 RAM 300~400MB, 무한 허용 시 OOM)

---

## 2. Phase 구성

총 7 Phase. 각 Phase는 독립적으로 커밋·테스트 가능하다.

| Phase | 내용 | 예상 LOC | 위험도 |
|---|---|---|---|
| 1 | `config.py` 멀티화 | ~80 | 낮음 |
| 2 | 기존 `settings.json` 마이그레이션 스크립트 | ~50 | 낮음 |
| 3 | `auth.py` 신설 + 로그인 검증 | ~150 | 중간 |
| 4 | `SessionContext` + `SchedulerRegistry` (AppState 리팩토링) | ~200 | **높음** |
| 5 | REST API에 `current_user` 주입 | ~100 | 중간 |
| 6 | WebSocket 사용자 스코프 분리 | ~80 | 중간 |
| 7 | `templates/index.html` 로그인 UI + 동시성 제한 | ~150 | 낮음 |

---

## Phase 1 — `config.py` 멀티화

### 목표

`config.load()` / `config.save()`에 `username` 인자를 추가하고, 저장 경로를 사용자별로 분리한다.

### 변경 사항

**디렉토리 구조**
```
data/
├── settings.json                          ← 사용하지 않게 됨 (Phase 2에서 마이그레이션)
└── users/
    └── <username>/
        └── settings.json
```

**`config.py` 수정**

- `_user_dir(username: str) -> Path` 헬퍼 추가
  - path traversal 방어: `re.match(r'^[A-Za-z0-9_.-]+$', username)` 통과 못하면 `ValueError`
  - `SETTINGS_DIR` 환경변수 존중 (기존 동작 유지)
- `load(username: str) -> dict` — `data/users/<username>/settings.json` 읽기
- `save(username: str, settings: dict)` — `data/users/<username>/settings.json` 쓰기
- `encode_password` / `decode_password`는 그대로 유지

### 프롬프트

```
Phase 1을 진행해. config.py의 load/save에 username 파라미터를 추가하고,
저장 경로를 data/users/<username>/settings.json으로 분리해.

요구사항:
- _user_dir(username) 헬퍼를 만들고 path traversal을 정규식으로 막을 것
- SETTINGS_DIR 환경변수는 기존처럼 존중 (data/ 대신 그 경로 아래에 users/ 디렉토리)
- encode_password / decode_password는 시그니처 그대로 유지
- 이 단계에서는 web_server.py를 건드리지 않음 (다음 Phase에서 호출부 수정)

수정 끝나면 변경된 함수 시그니처를 요약해서 보여줘.
```

### 검증

```bash
python -c "import config; config.save('testuser', {'username':'testuser', 'facility':'속초수련원'}); print(config.load('testuser'))"
ls -la data/users/testuser/
```

→ `settings.json`이 사용자 디렉토리에 생성되어야 함.
→ 잘못된 username (`../etc`, `a/b`)을 넣으면 ValueError가 나야 함.

---

## Phase 2 — 기존 `settings.json` 마이그레이션

### 목표

운영 중인 단일 `data/settings.json`을 `data/users/<username>/settings.json`으로 자동 이전한다.

### 변경 사항

**새 파일: `migrate.py`** (일회성 스크립트)
- `data/settings.json`이 존재하면 `username` 필드를 읽음
- 해당 사용자 디렉토리로 복사
- 원본은 `data/settings.json.migrated.<timestamp>`로 이름 변경 (삭제하지 않음)

### 프롬프트

```
Phase 2 진행. migrate.py를 만들어줘. 동작:
1. data/settings.json이 존재하면 그 안의 username 필드를 읽기
2. config.save(username, settings)로 새 위치에 저장
3. 원본은 data/settings.json.migrated.<unix_timestamp>로 rename (삭제 금지)
4. 이미 마이그레이션된 흔적이 있으면 skip하고 로그만 남길 것
5. CLI로 `python migrate.py` 실행하면 끝나는 단순 스크립트

추가로 Dockerfile/docker-compose.yml에는 손대지 마. 마이그레이션은 수동으로 한 번 실행할 거야.
```

### 검증

```bash
python migrate.py
ls data/                                # settings.json.migrated.* 가 생기고
ls data/users/<원래username>/           # settings.json 이 생겼는지 확인
```

---

## Phase 3 — `auth.py` 신설 + 로그인 검증

### 목표

연수원 사이트 자격(아이디/비밀번호)을 그대로 앱 로그인 자격으로 재사용. 세션 쿠키 발급.

### 변경 사항

**새 파일: `auth.py`**

- `SESSION_COOKIE_NAME = "yeonsubot_session"`
- 메모리 세션 저장소: `_sessions: dict[str, SessionInfo]` (`session_id` → `{username, created_at, last_seen_at}`)
- `create_session(username) -> session_id` — `secrets.token_urlsafe(32)`
- `resolve_session(session_id) -> str | None` — 만료 검사 (예: 7일)
- `destroy_session(session_id)`
- FastAPI dependency: `current_user(session_id: str = Cookie(None)) -> str` — 실패 시 401

**`checker.py` 활용**

로그인 검증을 위해 `BrowserSession`을 새로 띄우는 건 무겁다. 대안:
- **선택 A (간단·느림)**: 매 로그인마다 `BrowserSession.start()`를 짧게 띄워 검증
- **선택 B (빠름·복잡)**: 연수원 사이트의 로그인 API만 `requests`로 직접 호출 (checker.py에서 로그인 부분만 분리 필요)

→ **권장: A로 시작**. 친구 몇 명 쓰는 규모면 OK. 로그인은 자주 일어나는 동작이 아님.

**`web_server.py`에 추가 (이 Phase에서는 endpoint만, 다른 곳은 안 건드림)**

- `POST /api/auth/login` — `{username, password}` → `BrowserSession`으로 검증 → 성공 시 Set-Cookie
- `POST /api/auth/logout` — 세션 파기 + 쿠키 삭제
- `GET /api/auth/me` — 현재 로그인 정보 (없으면 401)

### 프롬프트

```
Phase 3 진행. 다음을 만들어:

1. auth.py 신설
   - 메모리 dict로 세션 관리 (재시작 시 모두 무효, 친구용이라 OK)
   - create_session / resolve_session / destroy_session
   - current_user FastAPI dependency (Cookie 기반, 실패 시 401)
   - 세션 유효기간 7일

2. web_server.py에 인증 엔드포인트 3개 추가
   - POST /api/auth/login: username/password 받아서 checker.BrowserSession.start()로 검증.
     성공하면 세션 생성하고 쿠키 발급. 실패하면 401.
   - POST /api/auth/logout
   - GET /api/auth/me
   
3. 이 Phase에서는 기존 /api/start, /api/stop 등은 건드리지 마. 다음 Phase 작업.

로그인 검증용 BrowserSession은 검증 후 즉시 stop() 해야 메모리 누수 없음.
검증 끝나면 사용한 비밀번호를 config.save()로 저장도 같이 해줘 (인코딩된 채로).
```

### 검증

```bash
curl -X POST http://localhost:8000/api/auth/login -H "Content-Type: application/json" -d '{"username":"테스트","password":"..."}' -c cookies.txt
curl http://localhost:8000/api/auth/me -b cookies.txt
```

---

## Phase 4 — `SessionContext` + `SchedulerRegistry` (⚠️ 핵심)

### 목표

`AppState`(전역 1개)를 `SessionContext`(사용자 1명분) × N개로 분리한다.

### 변경 사항

**`web_server.py` 구조 변경**

```python
class SessionContext:
    """사용자 1명분 상태."""
    def __init__(self, username: str):
        self.username = username
        self.scheduler = MonitorScheduler()
        self.ws_clients: set[WebSocket] = set()
        self.log_buffer: deque[dict] = deque(maxlen=LOG_BUFFER_MAX)
        self.current_status = "중지"
        self.last_check_at: str | None = None
        self.last_result: dict | None = None
        # scheduler 콜백을 self의 메서드로 연결
        self.scheduler.on_status_change = self._on_status_change
        # ... 나머지 콜백도 self 메서드로
    
    def _on_status_change(self, status): ...  # 기존 AppState 메서드를 그대로 이전
    def _broadcast(self, message): ...        # ws_clients가 self.ws_clients로
    async def _async_broadcast(self, message): ...

class SchedulerRegistry:
    def __init__(self, max_concurrent: int = 5):
        self._contexts: dict[str, SessionContext] = {}
        self._lock = threading.Lock()
        self._max_concurrent = max_concurrent
        self.loop: asyncio.AbstractEventLoop | None = None
    
    def get_or_create(self, username: str) -> SessionContext:
        with self._lock:
            if username not in self._contexts:
                running_count = sum(1 for c in self._contexts.values() if c.scheduler.is_running)
                if running_count >= self._max_concurrent:
                    raise HTTPException(503, f"동시 실행 한도({self._max_concurrent})에 도달했습니다.")
                ctx = SessionContext(username)
                ctx.loop = self.loop  # SessionContext도 loop 참조 필요
                self._contexts[username] = ctx
            return self._contexts[username]
    
    def get(self, username: str) -> SessionContext | None: ...
    def drop(self, username: str): ...  # 로그아웃 시 정리

registry = SchedulerRegistry()
```

**`WebSocketLogHandler`도 사용자별로 분리** — 이게 까다로움.

- 현재 `WebSocketLogHandler`는 모든 logger 메시지를 잡아서 단일 `state.log_buffer`에 넣음.
- `MonitorScheduler` 내부 로그도 `logger = logging.getLogger(__name__)`로 찍히므로 어느 사용자 것인지 구분이 안 됨.
- **해결**: `LogContext` ContextVar(또는 threading.local) 도입. 각 워커 스레드 진입 시 `username`을 ContextVar에 세팅. `WebSocketLogHandler.emit()`에서 ContextVar를 읽어 해당 SessionContext의 log_buffer로 라우팅.

### 프롬프트 (가장 중요한 단계)

```
Phase 4 진행. 이게 가장 큰 리팩토링이야. 다음 순서로:

1. web_server.py에 SessionContext 클래스 신설.
   - 기존 AppState의 필드/메서드를 거의 그대로 이전 (단, scheduler 콜백을 self의 메서드로 바인딩)
   - __init__에 username 필수
   - loop는 SchedulerRegistry에서 주입

2. SchedulerRegistry 클래스 신설.
   - get_or_create(username), get(username), drop(username)
   - max_concurrent (기본 5) 상한 검사
   - threading.Lock으로 동시 생성 방지

3. 기존 전역 state 변수를 registry로 교체.
   - 이 Phase에서는 엔드포인트 호출부는 아직 username을 모르므로,
     임시로 registry.get_or_create("__legacy__") 같은 dummy를 써서 컴파일/기동만 되게 만들어.
     실제 사용자 라우팅은 Phase 5에서.

4. WebSocketLogHandler 사용자 라우팅:
   - contextvars.ContextVar("yeonsubot_user") 도입
   - MonitorScheduler._worker_loop 진입 시 ContextVar에 username을 set 해야 함
     → scheduler.py도 일부 수정 필요. start()에 username을 받도록 추가하고,
       _worker_loop에서 contextvar token = USER_CTX.set(self._username) 처리.
   - WebSocketLogHandler.emit()에서 USER_CTX.get(None)을 읽어 registry.get(username)으로 라우팅.
     ContextVar에 값이 없으면 (예: 워커 스레드 밖에서 찍힌 로그) 전역 로그로 처리 → 일단 무시 또는 stderr.

5. lifespan에서 registry.loop = asyncio.get_running_loop() 세팅.

수정 끝나면:
- 새 클래스 구조 다이어그램을 텍스트로 그려줘
- 컨테이너 재기동 후 기존 /api/start (dummy user)가 동작하는지 수동 테스트 가능한 상태여야 함
```

### 검증

이 Phase는 외부 동작이 거의 안 바뀜 (`__legacy__` 더미 사용자 하나로 기존처럼 돌아야 함). 회귀 테스트가 핵심:

```bash
docker compose up --build
# 브라우저에서 기존처럼 시작 → 모니터링이 정상 동작하는지 확인
# 로그가 WebSocket으로 잘 들어오는지 확인
```

---

## Phase 5 — REST API에 `current_user` 주입

### 목표

`__legacy__` 더미를 제거하고 실제 로그인 사용자로 모든 엔드포인트를 스코프한다.

### 변경 사항

**`web_server.py`의 각 엔드포인트**

```python
@app.post("/api/start")
async def api_start(request: Request, user: str = Depends(current_user)):
    ctx = registry.get_or_create(user)
    if ctx.scheduler.is_running:
        raise HTTPException(409, "이미 실행 중입니다.")
    # ... config.load(user) / config.save(user, ...)
    ctx.scheduler.start(..., username=user, ...)

@app.post("/api/stop")
async def api_stop(user: str = Depends(current_user)):
    ctx = registry.get(user)
    if ctx: ctx.scheduler.stop()
    ...

@app.get("/api/status")
async def api_status(user: str = Depends(current_user)):
    ctx = registry.get(user)
    return _status_payload(ctx)  # ctx 기반으로 변경

@app.get("/api/settings")
async def api_get_settings(user: str = Depends(current_user)):
    settings = config.load(user)
    ...

@app.post("/api/slack/test"): ...
@app.post("/api/logs/clear")  → ctx.log_buffer.clear()
```

### 프롬프트

```
Phase 5 진행. 모든 /api/* 엔드포인트에 Depends(current_user)를 주입하고,
__legacy__ 더미 사용자 코드를 제거해.

- /api/start, /api/stop, /api/status, /api/settings, /api/logs/clear: user 필수
- /api/slack/test: user 필수 (다른 사람의 Slack을 함부로 못 쏘게)
- /api/auth/login, /api/auth/logout, /api/auth/me: user 불필요 (login은 user를 만드는 동작 자체)
- 정적 페이지 GET /: user 불필요. 클라이언트가 알아서 /api/auth/me로 로그인 상태 확인

config.load/save 호출부 전부 user 인자를 넣어줘.

수정 후 다음을 보여줘:
- 변경된 엔드포인트 목록과 인증 필요 여부 표
```

### 검증

```bash
# 인증 없이 호출 → 401
curl http://localhost:8000/api/status
# 로그인 후 호출 → 200
curl -X POST .../api/auth/login -d '{...}' -c c.txt
curl http://localhost:8000/api/status -b c.txt
```

---

## Phase 6 — WebSocket 사용자 스코프 분리

### 목표

WebSocket 연결을 사용자 단위로 분리. 로그/상태 브로드캐스트가 해당 사용자에게만 가도록.

### 변경 사항

**`web_server.py`의 `/ws` 엔드포인트**

```python
@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket, session_id: str | None = Cookie(None, alias="yeonsubot_session")):
    username = resolve_session(session_id) if session_id else None
    if not username:
        await ws.close(code=4401)  # Unauthorized
        return
    
    await ws.accept()
    ctx = registry.get_or_create(username)
    ctx.ws_clients.add(ws)
    try:
        # ctx.log_buffer를 그대로 보냄 (사용자 본인 것만)
        for entry in list(ctx.log_buffer):
            await ws.send_json(entry)
        await ws.send_json({"type": "status", "status": ctx.current_status, "last_check_at": ctx.last_check_at})
        while True:
            try: await ws.receive_text()
            except WebSocketDisconnect: break
    finally:
        ctx.ws_clients.discard(ws)
```

**`SessionContext._async_broadcast`** — `state.ws_clients` 대신 `self.ws_clients`만 순회 (Phase 4에서 이미 처리되었어야 함, 여기서 재확인).

### 프롬프트

```
Phase 6 진행. WebSocket을 사용자 스코프로 분리.

1. /ws 엔드포인트에 쿠키 기반 인증 추가. 세션 없으면 4401로 close.
2. ws.accept() 직후 registry.get_or_create(username)으로 ctx 획득, ctx.ws_clients.add(ws).
3. 연결 직후 ctx.log_buffer만 전송 (다른 사용자 로그 노출 금지).
4. SessionContext._async_broadcast가 정말 self.ws_clients만 쓰는지 재검토.

추가로:
- 클라이언트(templates/index.html)는 아직 인증 UI가 없으니, 이 Phase에서는 WS가 4401로 닫혀도 OK.
  Phase 7에서 UI 추가 후 정상화될 것.
- 다만 디버깅 편의를 위해 콘솔에 close 사유가 잘 보이게.

테스트 시나리오를 알려줘:
- 두 명의 사용자가 각각 다른 브라우저에서 로그인 → 동시에 /api/start →
  각자의 WS에 각자 로그만 들어오는지 어떻게 확인할지
```

### 검증

```bash
# 시크릿 창 2개로 각각 다른 계정 로그인
# 각각 /api/start
# 두 창의 로그가 섞이지 않는지 확인
docker compose logs -f
```

---

## Phase 7 — `templates/index.html` 로그인 UI + 마무리

### 목표

프론트엔드에 로그인 화면 추가, 현재 사용자 표시, 로그아웃.

### 변경 사항

**`templates/index.html`**

- 최초 로드 시 `GET /api/auth/me` 호출
  - 200이면 메인 화면
  - 401이면 로그인 화면 표시
- 로그인 폼: username/password → `POST /api/auth/login`
- 메인 화면 우상단에 사용자 표시 + 로그아웃 버튼
- 로그아웃: `POST /api/auth/logout` → 로그인 화면으로

**WebSocket 재연결**

- 로그인 성공 후에야 `new WebSocket(...)` 실행
- 로그아웃 시 ws.close()

**디자인 유지**

- 기존 `DESIGN.md`의 Apple 시스템(SF Pro, `#0071e3`, `#f5f5f7`) 토큰을 그대로 사용
- 로그인 카드 1개 가운데 정렬, 폰트/색상 일관

### 프롬프트

```
Phase 7 진행. templates/index.html에 로그인 UI를 추가.

요구사항:
1. 페이지 진입 시 GET /api/auth/me로 로그인 상태 확인.
   200이면 기존 메인 패널 표시, 401이면 로그인 카드 표시.
2. 로그인 카드: username, password, 로그인 버튼. 실패 시 빨간 인라인 에러.
3. 로그인 성공 시 WebSocket 연결 + 메인 패널 표시.
4. 메인 패널 우상단: "안녕하세요, <username>님" + 로그아웃 버튼.
5. 로그아웃: WS close → POST /api/auth/logout → 로그인 카드로.
6. 디자인 토큰은 DESIGN.md 그대로. 새 색/폰트 도입 금지.
7. 503 응답 (동시 실행 한도 초과)을 받았을 때 사용자에게 친절한 안내 메시지.

수정 끝나면 변경된 JS 함수 목록과 새로 추가된 DOM 영역을 요약해줘.
```

### 검증

전체 회귀 테스트:

1. 로그아웃 상태로 `/` 접속 → 로그인 카드
2. 잘못된 자격 → 에러 표시
3. 올바른 자격 → 메인 패널
4. 새 시크릿 창에서 다른 계정 로그인 → 두 사용자가 각자 모니터링 시작 가능
5. 동시 5명까지 OK, 6번째 → 503 안내
6. 로그아웃 → 로그인 카드로 복귀
7. 컨테이너 재기동 후 재로그인 → 설정이 복원되는지 (Phase 1 user별 settings.json 동작)

---

## Phase 8 — 동일 브라우저 프로필 다계정 지원

### 목표

같은 브라우저 프로필에서 창 2개를 열어 각각 다른 계정으로 로그인해도, 마지막 로그인 사용자의 쿠키가 다른 창을 덮어쓰지 않게 한다.

### 배경

현재 인증은 `yeonsubot_session` 쿠키 기반이다. 같은 Chrome 프로필의 두 창은 `127.0.0.1:8765` origin 쿠키를 공유하므로, 창 A에서 `gmsshs`로 로그인한 뒤 창 B에서 `jjn815`로 로그인하면 쿠키는 `jjn815` 세션으로 덮인다.

이 상태에서 창 A의 JS 메모리에는 `state.currentUser = "gmsshs"`가 남아 있고, 서버는 쿠키로 `jjn815`를 인증한다. 그래서 `/api/start`에서 body username과 인증 user가 달라 `"로그인 사용자와 요청 아이디가 다릅니다."`가 발생한다.

### 변경 사항

**인증 전달 방식 전환**

- 로그인 성공 시 서버가 `session_id`를 JSON 응답에 포함
- 프론트엔드는 `sessionStorage.setItem("yeonsubot_session", session_id)`로 창별 저장
- 모든 REST API 호출은 `X-YeonsuBot-Session` 헤더로 세션 전달
- 기존 쿠키는 호환성 fallback으로 남겨도 되지만, 프론트는 더 이상 쿠키에 의존하지 않음

**WebSocket 인증**

- 브라우저 WebSocket은 커스텀 헤더를 보낼 수 없으므로 query string으로 세션 전달
- 예: `/ws?session_id=<token>`
- 세션이 없거나 만료되면 `4401 authentication required`로 close

**프론트엔드**

- 공통 `apiFetch()` 헬퍼 추가
  - `sessionStorage`의 토큰을 읽어 `X-YeonsuBot-Session` 헤더 첨부
  - 401 응답 시 해당 창의 `sessionStorage`만 삭제하고 로그인 화면 표시
- `checkAuth()`는 `sessionStorage` 토큰이 없으면 즉시 로그인 화면 표시
- `connectWS()`는 `/ws?session_id=<token>`으로 연결
- `logout()`은 WS close → `POST /api/auth/logout` → `sessionStorage` 삭제 → 로그인 화면

### 프롬프트

```
Phase 8 진행. 같은 브라우저 프로필에서 창 2개를 각각 다른 계정으로 로그인하면
yeonsubot_session 쿠키를 공유해서 마지막 로그인 사용자로 덮이는 문제가 있다.
쿠키 기반 인증을 탭/창별 sessionStorage 토큰 기반 인증으로 바꿔줘.

요구사항:
1. POST /api/auth/login
   - 기존 세션 생성은 유지
   - 응답 JSON에 session_id를 포함
   - Set-Cookie는 남겨도 되지만 프론트는 더 이상 의존하지 않음

2. auth.py
   - current_user dependency가 X-YeonsuBot-Session 헤더를 우선 사용
   - 헤더가 없으면 기존 Cookie fallback 허용
   - resolve_session / destroy_session 시그니처는 유지

3. web_server.py
   - GET /api/auth/me는 X-YeonsuBot-Session 헤더로도 동작
   - POST /api/auth/logout도 X-YeonsuBot-Session 헤더로 해당 세션 파기
   - /ws는 WebSocket 커스텀 헤더를 못 쓰므로 query string session_id로 인증
     예: /ws?session_id=<token>
   - 세션 없거나 만료되면 4401 authentication required로 close

4. templates/index.html
   - 로그인 성공 시 sessionStorage.setItem('yeonsubot_session', session_id)
   - 모든 API 호출은 공통 apiFetch()를 통해 X-YeonsuBot-Session 헤더 첨부
   - checkAuth()는 sessionStorage 토큰이 없으면 로그인 화면 표시
   - connectWS()는 /ws?session_id=<token>으로 연결
   - logout()은 WS close → POST /api/auth/logout → sessionStorage 삭제 → 로그인 화면
   - 401 또는 WS 4401이면 해당 창의 sessionStorage만 삭제하고 로그인 화면으로 전환

5. 기존 멀티유저 로그 스코프는 유지
   - 각 창의 session_id가 resolve한 username의 SessionContext만 사용해야 함
   - 다른 사용자 로그가 섞이면 안 됨

수정 후 보여줘:
- 변경된 인증 흐름 요약
- 같은 Chrome 프로필 창 2개로 서로 다른 계정 로그인 테스트 절차
```

### 검증

1. 같은 Chrome 프로필에서 창 A/B를 열고 각각 다른 계정으로 로그인
2. 각 창 DevTools → Application → Session Storage에서 `yeonsubot_session` 값이 서로 다른지 확인
3. 각 창에서 `/api/auth/me`가 자기 username을 반환하는지 확인
4. 각 창에서 START 실행 시 `"로그인 사용자와 요청 아이디가 다릅니다."`가 발생하지 않는지 확인
5. 두 창에서 동시에 실행 후 각자의 WebSocket 로그만 보이는지 확인
6. 창 A 로그아웃이 창 B의 세션, WS, 실행 상태에 영향을 주지 않는지 확인

---

## 3. 위험 요소 및 대응

| 위험 | 영향 | 대응 |
|---|---|---|
| 동시 N명이 각자 Chromium 띄움 | RAM N × 400MB | `MAX_CONCURRENT_SESSIONS=5` 상한. README 갱신. |
| 로그 ContextVar가 워커 스레드에서 전파 안 됨 | 사용자 A 로그가 사용자 B에 노출 | `_worker_loop` 진입 즉시 `USER_CTX.set()`. 단위 테스트 작성 권장. |
| 로그인 검증 시 BrowserSession이 무거움 | 로그인 응답 지연 (~5-10초) | 사용자에게 로딩 표시. 추후 `requests` 기반 경량 검증으로 최적화 가능. |
| `__legacy__` 더미가 남으면 보안 구멍 | 인증 우회 | Phase 5 종료 후 grep으로 확인. PR 리뷰 체크리스트에 포함. |
| 세션이 메모리에만 있어 재시작 시 모두 로그아웃 | UX 저하 | 친구용 수용 가능. 필요 시 `data/sessions.json`에 영속화. |
| 같은 브라우저 프로필의 여러 창이 쿠키를 공유 | 창 A의 화면 사용자와 서버 인증 사용자가 달라짐 | Phase 8에서 `sessionStorage` 토큰 + `X-YeonsuBot-Session` 헤더로 창별 세션 분리. |
| 마이그레이션 후 원본 `settings.json`에 누가 또 쓰면? | 데이터 분기 | Phase 2 후 `data/settings.json`은 더 이상 읽지 않게 `config.py`에서 제거 확인. |

---

## 4. 작업 진행 명령 요약 (복붙용)

세션에서 순서대로:

```
Phase 1 진행해. (위 Phase 1 프롬프트 본문)
```

각 Phase 종료 시 Claude Code가 변경 요약을 출력하면 → 사용자가 수동 검증 → 다음 Phase 지시.

중간에 컨텍스트가 길어지면 `/compact` 후 새 세션에서 "MULTI_USER_PLAN.md 다시 읽고 Phase N부터 이어서"로 재개.

---

## 5. 최종 점검 체크리스트

- [ ] 두 사용자가 동시에 로그인해 각자 모니터링 시작 가능
- [ ] 사용자 A의 로그가 사용자 B의 화면에 절대 보이지 않음
- [ ] 사용자별 `data/users/<username>/settings.json`이 분리되어 저장됨
- [ ] 인증 없이 모든 `/api/*` 호출 시 401
- [ ] 동시 실행 한도 초과 시 503 + UI 안내
- [ ] 컨테이너 재시작 후 재로그인하면 직전 설정이 복원됨
- [ ] 로그아웃 시 WebSocket이 닫히고 세션이 파기됨
- [ ] 같은 Chrome 프로필 창 2개에서 서로 다른 계정으로 로그인해 동시에 START 가능
- [ ] README.md 갱신: "여러 사용자 동시 사용 가능, 동시 실행 한도 N명"
