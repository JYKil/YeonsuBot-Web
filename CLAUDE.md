# 서울특별시 연수원 자동 예약 (Yeonsu-Bot Web)

## 프로젝트 개요

서울시 공무원 연수원(https://yeonsu.eseoul.go.kr/) 예약 가능 날짜를 주기적으로 모니터링하고, 빈방 발견 시 자동 예약하는 **웹 앱** (FastAPI + WebSocket). 본인 1명 전용, 단일 슬롯 구조. Oracle Cloud Free Tier VM에 Docker로 배포.

이전 CustomTkinter 데스크톱 버전에서 웹으로 전환됨. 비즈니스 로직(`checker.py`, `scheduler.py`, `notifier.py`, `facilities.py`)은 GUI 의존성이 없어 그대로 재사용하고 GUI 레이어만 FastAPI + HTML로 교체.

## 아키텍처

- **main.py**: FastAPI 진입점 — uvicorn으로 `web_server:app` 실행
- **web_server.py**: FastAPI 앱. `AppState`(scheduler + ws_clients + log_buffer + current_status + last_check_at), `WebSocketLogHandler`(로깅 → WS 브로드캐스트, `loop.call_soon_threadsafe()`로 워커 스레드 안전), lifespan 컨텍스트(종료 시 `scheduler.stop()` + join). REST: `/api/status`, `/api/settings`, `/api/start` (409), `/api/stop`, `/api/slack/test`. WebSocket: `/ws` (연결 시 log_buffer 즉시 전송).
- **templates/index.html**: 단일 패널 UI (Vanilla JS). 상태+액션 → 폼 → 로그 3단 계층. 시작/중지 토글 버튼. 자동 스크롤 pause, 토스트 알림, 3초 WS 재연결. DESIGN.md Apple 시스템 토큰 적용.
- **mockups/index.html**: 정적 디자인 목업 (참고용, 실제 앱 아님).
- **checker.py**: `BrowserSession` 클래스. Playwright로 로그인 → 연수원 선택 → 달력 조회 → 자동 예약 (7단계 플로우: 연수원 선택 → 달력 체크인/체크아웃 날짜 클릭 → hidden 필드 동기화 → 선택일로 예약하기 → 기관배정 팝업 닫기 → 객실선택하기 → 예약하기 → 예약안내 팝업 동의). Playwright 네이티브 클릭(trusted event) 사용. 체크아웃은 1박/다박 무관하게 항상 명시적 클릭하며, 다음날 예약 불가 시 사이트 자동 설정 허용. `check_in_day_hidden` → `check_in_day` 필드 동기화 필수. `stop_event`를 받아 주요 단계마다 중지 체크. **Docker 환경에서는 `playwright install chrome`으로 설치한 실제 Google Chrome을 `channel="chrome"`으로 사용**하며 `--no-sandbox --disable-dev-shm-usage` 옵션 적용.
- **scheduler.py**: `MonitorScheduler` 클래스. 워커 스레드에서 `BrowserSession`을 소유하고 주기적 체크 + 예약 시도. `stop_event`를 `book()`에 전달하여 즉시 중지 대응. 변경 없음.
- **notifier.py**: Slack Incoming Webhook 알림 (빈방 발견, 예약 성공/실패, 테스트). 변경 없음.
- **config.py**: settings.json 저장/불러오기, 비밀번호 Base64 인코딩. **`SETTINGS_DIR` 환경변수**로 Docker 볼륨 경로 주입 가능.
- **facilities.py**: 10개 연수원 이름↔코드 매핑. 변경 없음.
- **plan.md / to-do.md / DESIGN.md**: 웹 전환 계획, 작업 목록, Apple 디자인 시스템.

## 실행 방법

```bash
# 로컬 (Docker 없이) — pyproject.toml 기반
uv sync                  # 최초 1회
uv run python main.py    # → http://localhost:8000

# Docker
docker compose up --build
```

## 배포 환경

- **VM**: Oracle Cloud Free Tier, `VM.Standard.A1.Flex` (ARM 4 OCPU / 24GB), Ubuntu 22.04
- **Public IP**: `132.226.23.181`
- **SSH**: 포트 `2222` (집 네트워크에서 22번 차단으로 대체 포트 사용)
- **접속**: `ssh yeonsu` (Mac `~/.ssh/config` 별칭 설정 완료)
- **앱 URL**: http://132.226.23.181:8000

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
