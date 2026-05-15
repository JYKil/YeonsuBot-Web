# 서울특별시 연수원 자동 예약 (Yeonsu-Bot Web)

## 프로젝트 개요

서울시 공무원 연수원(https://yeonsu.eseoul.go.kr/) 예약 가능 날짜를 주기적으로 모니터링하고, 빈방 발견 시 자동 예약하는 **웹 앱** (FastAPI + WebSocket). 최대 3명이 동시에 각자 계정으로 로그인해 독립적으로 봇을 운영할 수 있는 멀티유저 구조. Beelink EQR6 미니 PC(Ubuntu)에 Docker로 배포, GitLab + Jenkins CI/CD.

이전 CustomTkinter 데스크톱 버전에서 웹으로 전환됨. 비즈니스 로직(`checker.py`, `scheduler.py`, `notifier.py`, `facilities.py`)은 GUI 의존성이 없어 그대로 재사용하고 GUI 레이어만 FastAPI + HTML로 교체.

## 아키텍처

- **main.py**: FastAPI 진입점 — uvicorn으로 `web_server:app` 실행
- **web_server.py**: FastAPI 앱. `SessionContext`(사용자 1명분 scheduler + ws_clients + log_buffer + 상태)를 `SchedulerRegistry`가 username 키로 관리. `WebSocketLogHandler`는 `USER_CTX` ContextVar를 읽어 해당 사용자의 log_buffer로만 라우팅. lifespan 컨텍스트(종료 시 전체 컨텍스트 stop + join). REST: `/api/auth/*`, `/api/status`, `/api/settings`, `/api/start` (409), `/api/stop`, `/api/logs/clear`, `/api/admin/sessions`. HTML: `/`, `/admin`. WebSocket: `/ws?session_id=<token>` (연결 시 사용자 본인 log_buffer만 즉시 전송).
- **auth.py**: 메모리 세션 관리. `create_session` / `resolve_session` / `destroy_session` (7일 TTL, 만료 자동 정리). `current_user` FastAPI dependency — `X-YeonsuBot-Session` 헤더 우선, Cookie fallback. `current_admin` FastAPI dependency — `ADMIN_PASSWORD` 환경변수 + `X-YeonsuBot-Admin-Password` 헤더 비교. `admin_session_snapshot()`은 token 없이 username별 세션 수/최초 로그인/최근 로그인/마지막 활동을 집계. 동시 로그인 한도 `MAX_CONCURRENT_USERS=3` 검사.
- **log_context.py**: `USER_CTX = ContextVar("yeonsubot_user")` — 워커 스레드별 username을 로그 핸들러에 전달하는 컨텍스트 변수.
- **templates/index.html**: 멀티유저 UI (Vanilla JS). 로그인 카드 → 메인 패널(상태+액션 → 폼 → 로그) 전환. `apiFetch()` 헬퍼로 모든 API 호출에 `X-YeonsuBot-Session` 헤더 자동 첨부. `sessionStorage`로 창별 세션 격리 (같은 브라우저 프로필의 여러 창에서 서로 다른 계정 동시 사용 가능). WS 연결은 `/ws?session_id=<token>`.
- **templates/admin.html**: Admin 현황판 UI (Vanilla JS). `/admin`에서 admin 비밀번호 입력 → `/api/admin/sessions` 호출. 읽기 전용이며 계정명, 최근 로그인, 실행 여부, 현재 상태, 모니터링 횟수만 표시. admin 비밀번호는 브라우저 저장소에 저장하지 않고 JS 메모리 변수로만 유지.
- **mockups/index.html**: 정적 디자인 목업 (참고용, 실제 앱 아님).
- **checker.py**: `BrowserSession` 클래스. Playwright로 로그인 → 연수원 선택 → 달력 조회 → 자동 예약 (7단계 플로우: 연수원 선택 → 달력 체크인/체크아웃 날짜 클릭 → hidden 필드 동기화 → 선택일로 예약하기 → 기관배정 팝업 닫기 → 객실선택하기 → 예약하기 → 예약안내 팝업 동의). Playwright 네이티브 클릭(trusted event) 사용. 체크아웃은 1박/다박 무관하게 항상 명시적 클릭하며, 다음날 예약 불가 시 사이트 자동 설정 허용. `check_in_day_hidden` → `check_in_day` 필드 동기화 필수. `stop_event`를 받아 주요 단계마다 중지 체크. **Linux/Docker 환경에서는 Playwright 내장 Chromium을 사용**하며 `--no-sandbox --disable-dev-shm-usage` 옵션 적용. ARM64에서는 Google Chrome 미지원으로 Chromium 사용 필수.
- **scheduler.py**: `MonitorScheduler` 클래스. 워커 스레드에서 `BrowserSession`을 소유하고 주기적 체크 + 예약 시도. START마다 `_cycle_count`를 0으로 리셋하고 체크 진입 시 1씩 증가, STOP 또는 예약 성공 시 다시 0으로 초기화. `stop_event`를 `book()`에 전달하여 즉시 중지 대응. `_worker_loop` 진입/종료 시 `USER_CTX` 설정/리셋.
- **config.py**: 사용자별 설정 저장/불러오기. 경로: `data/users/<username>/settings.json`. `load(username)` / `save(username, settings)`. path traversal 정규식 방어. 비밀번호 Base64 인코딩. **`SETTINGS_DIR` 환경변수**로 Docker 볼륨 경로 주입 가능.
- **migrate.py**: 일회성 마이그레이션 스크립트. 기존 단일 `data/settings.json` → `data/users/<username>/settings.json`으로 이전. 원본은 `.migrated.<timestamp>`로 rename.
- **notifier.py**: 알림 모듈 (현재 미사용, 텔레그램 전환 예정).
- **facilities.py**: 10개 연수원 이름↔코드 매핑.
- **plan.md / to-do.md / DESIGN.md**: 웹 전환 계획, 작업 목록, Apple 디자인 시스템.

## 실행 방법

```bash
# 로컬 (Docker 없이) — pyproject.toml 기반
uv sync                  # 최초 1회
uv run python main.py    # → http://localhost:3000

# Docker
docker compose up --build

# 로컬 디버깅 (headful 모드 — 브라우저 창 띄워서 DOM/JS 동작 확인)
HEADLESS=false uv run python main.py
```

Admin 현황판을 로컬에서 확인하려면 `ADMIN_PASSWORD`를 설정하고 `/admin`으로 접속:

```bash
ADMIN_PASSWORD=원하는관리자비밀번호 uv run python main.py
# http://localhost:3000/admin
```

## 배포 환경

- **서버**: Beelink EQR6 미니 PC, Ubuntu, x86_64
- **LAN IP**: `192.168.75.205`
- **외부 도메인**: `kilga-server.duckdns.org` (DuckDNS)
- **앱 URL (LAN)**: http://192.168.75.205:3000
- **앱 URL (외부)**: http://kilga-server.duckdns.org:3000
- **GitLab**: http://192.168.75.205:8929 / http://kilga-server.duckdns.org:8929
- **Jenkins**: http://192.168.75.205:8080 / http://kilga-server.duckdns.org:8080

## 재배포 흐름 (CI/CD)

GitLab push → Jenkins 웹훅 자동 트리거 → 빌드 + 배포 + 헬스체크

```bash
# 로컬에서 커밋 + push 만 하면 자동 배포됨
git push origin master
```

Jenkins 파이프라인 (`Jenkinsfile`):
1. 준비 — `mkdir -p data` (볼륨 디렉토리 보장)
2. 빌드 — `docker compose build --pull`
3. 배포 — `docker compose up -d --force-recreate`
4. 헬스체크 — `curl http://localhost:3000/api/status`

배포 디렉토리: `/opt/yeonsubot` (settings.json 볼륨이 이 경로 아래 영속)

Admin 현황판 운영 설정:

```bash
cd /opt/yeonsubot
cp .env.example .env
nano .env  # ADMIN_PASSWORD=원하는관리자비밀번호
docker compose up -d --force-recreate
```

`docker-compose.yml`은 optional `.env`를 읽는다. `.env`가 없거나 `ADMIN_PASSWORD`가 비어 있으면 `/admin` HTML은 열리지만 `/api/admin/sessions`는 503으로 차단된다.

운영 중 버그 수정 이력은 `BUGFIX_LOG.md` 참조.

## 디자인

- Apple 시스템 기반 (SF Pro Text/Display, `#0071e3`, `#f5f5f7`, `#1d1d1f`)
- 정보 계층: 상태+액션 → 폼 → 로그
- 시작/중지는 같은 자리 토글, 예약 성공 시 자동 중지
- Shadow 없음, flat 디자인 (배경색 대비로 분리)
- 세부 토큰은 `DESIGN.md` 및 `plan.md` "디자인 시스템 토큰" 섹션 참조

## gstack

- 웹 브라우징은 항상 `/browse` 스킬을 사용할 것
- `mcp__claude-in-chrome__*` 도구는 절대 사용하지 말 것
- 사용 가능한 스킬: /office-hours, /plan-ceo-review, /plan-eng-review, /plan-design-review, /design-consultation, /design-shotgun, /design-html, /review, /ship, /land-and-deploy, /canary, /benchmark, /browse, /connect-chrome, /qa, /qa-only, /design-review, /setup-browser-cookies, /setup-deploy, /retro, /investigate, /document-release, /codex, /cso, /autoplan, /careful, /freeze, /guard, /unfreeze, /gstack-upgrade, /learn
- gstack 스킬이 작동하지 않으면 `cd .claude/skills/gstack && ./setup` 을 실행하여 바이너리를 빌드하고 스킬을 등록할 것

## Skill routing

When the user's request matches an available skill, ALWAYS invoke it using the Skill
tool as your FIRST action. Do NOT answer directly, do NOT use other tools first.
The skill has specialized workflows that produce better results than ad-hoc answers.

Key routing rules:
- Product ideas, "is this worth building", brainstorming → invoke office-hours
- Bugs, errors, "why is this broken", 500 errors → invoke investigate
- Ship, deploy, push, create PR → invoke ship
- QA, test the site, find bugs → invoke qa
- Code review, check my diff → invoke review
- Update docs after shipping → invoke document-release
- Weekly retro → invoke retro
- Design system, brand → invoke design-consultation
- Visual audit, design polish → invoke design-review
- Architecture review → invoke plan-eng-review
- Save progress, checkpoint, resume → invoke checkpoint
- Code quality, health check → invoke health
