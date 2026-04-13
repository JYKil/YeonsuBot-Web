# YeonsuBot 웹 전환 — 작업 목록

## 선행 작업

- [ ] **`/plan-design-review` 실행** — `DESIGN.md` (Apple 디자인 시스템)를 기준으로 디자인 리뷰 진행. 1슬롯 단일 패널 UI에 맞춰 토큰/컴포넌트 스펙 확정.

---

## 확정된 설계 결정 (2026-04-14)

| 항목 | 결정 |
|------|------|
| 사용 주체 | 본인 1명 전용, 한 번에 한 세션 |
| 봇 슬롯 수 | **1개 고정** |
| 웹앱 인증 | 없음 — 로컬 전용, URL 알면 접근 |
| 실시간 로그 | WebSocket (FastAPI) |
| 예약 성공 후 | 자동 중지 + "예약완료" badge |
| UI 레이아웃 | 단일 패널 — 설정 좌(40%) / 로그 우(60%) |
| 동시 실행 방지 | `/api/start` 재호출 시 409 응답 |
| 디자인 시스템 | DESIGN.md Apple 시스템 (SF Pro, #0071e3, #f5f5f7) |

---

## Phase 1: 핵심 로직 수정

- [ ] **`config.py`** — Docker 볼륨 지원 (최소 변경)
  - `base_dir`를 `os.environ.get("SETTINGS_DIR", ...)` 로 변경
  - `SETTINGS_FILE = os.path.join(base_dir, "settings.json")`
  - `load()` / `save()` 시그니처 **변경 없음**

- [ ] **`checker.py`** — Linux headless 환경 대응
  - `_detect_browser_channel()`: 브라우저 못 찾으면 예외 대신 `None` 반환
  - `BrowserSession.start()`: `channel=None` 시 내장 Chromium 사용
  - launch 옵션에 `--no-sandbox`, `--disable-dev-shm-usage` 추가

- [ ] **`notifier.py`** — **변경 없음**

- [ ] **`scheduler.py`, `facilities.py`** — **변경 없음**

---

## Phase 2: 백엔드 구현

- [ ] **`web_server.py`** 신규 생성 — FastAPI 앱
  - `AppState` 클래스: `scheduler`, `ws_clients: set[WebSocket]`, `log_buffer: deque(maxlen=200)`, `current_status`
  - `WebSocketLogHandler` (logging → `ws_clients` 브로드캐스트, `loop.call_soon_threadsafe()`)
  - lifespan 컨텍스트 (앱 종료 시 `scheduler.stop()` + `join(timeout=15)`)
  - REST 엔드포인트:
    - `GET /api/status` → `{running, status, last_result}`
    - `GET /api/settings` → 설정 로드 (비밀번호 마스킹)
    - `POST /api/start` → 설정 저장 + `scheduler.start()` (이미 실행 중이면 409)
    - `POST /api/stop` → `scheduler.stop()`
    - `POST /api/slack/test` → Slack 웹훅 테스트
  - WebSocket 엔드포인트: `WS /ws` (연결 시 `log_buffer` 즉시 전송)
  - scheduler 콜백 연결 (on_status_change, on_booking_result, on_error)

- [ ] **`main.py`** 교체 — FastAPI 진입점
  - 기존 CustomTkinter 코드 제거
  - `uvicorn.run(app, host="0.0.0.0", port=8000)` 로 변경

---

## Phase 3: 프론트엔드

> **디자인 스펙**: `plan.md` → "프론트엔드 (단일 패널, Vanilla JS)" 섹션 참조.
> 토큰/컴포넌트 확정은 선행 `/plan-design-review` 결과를 반영.

- [ ] **`templates/index.html`** 신규 생성 — 단일 페이지 UI
  - **레이아웃**: 다크 nav 바 + 설정 패널(좌 40%) / 로그 뷰어(우 60%) 2열
  - **디자인 토큰**: `plan.md` 토큰 표 그대로 CSS 변수로 선언
    - `--color-bg: #f5f5f7`, `--color-accent: #0071e3`, `--color-surface-dark: #1d1d1f`
    - nav: `background: rgba(0,0,0,0.8)`, `backdrop-filter: saturate(180%) blur(20px)`
  - 설정 폼: 아이디, 비밀번호(보기 토글), 연수원 드롭다운, 체크인/아웃 날짜, 점검주기
    - 체크인 변경 시 체크아웃 자동 +1일
  - 상태 뱃지: 색 + 텍스트 동시 표시 (접근성), `role="status"`, `aria-live="polite"`
  - 버튼: 시작(Apple Blue), 중지(dark), 로그 지우기 — 최소 44px 터치 타겟
  - 로그 영역: 어두운 배경 `#1d1d1f`, 13px monospace, 자동 스크롤
  - WS: 로드 시 `/ws` 단일 연결, 끊김 시 3초 후 자동 재연결 + `log_buffer` 즉시 수신
  - 로드 시 `GET /api/status`로 상태 동기화
  - 예약 성공 시: "예약완료" badge + 자동 중지 반영
  - Slack 테스트 버튼 (설정 패널 하단)

---

## Phase 4: 패키지 및 Docker

- [ ] **`requirements.txt`** 업데이트
  - 추가: `fastapi>=0.109.0`, `uvicorn[standard]>=0.27.0`
  - 제거: `customtkinter`, `tkcalendar`, `pyinstaller`

- [ ] **`Dockerfile`** 신규 생성
  - 베이스: `mcr.microsoft.com/playwright/python:v1.40.0-jammy`
  - `requirements.txt` 설치
  - `/data` 볼륨, `SETTINGS_DIR` 환경변수 설정
  - `EXPOSE 8000`, CMD 설정

- [ ] **`docker-compose.yml`** 신규 생성
  - `restart: unless-stopped`
  - `shm_size: "256mb"` (단일 Chromium 인스턴스)
  - `./data:/data` 볼륨 마운트

- [ ] **`.env.example`** 신규 생성

- [ ] **`gui.py`** 삭제

---

## Phase 5: Oracle Cloud 배포

- [ ] Oracle Cloud 계정 생성 및 Free Tier VM 생성
  - Shape: `VM.Standard.A1.Flex` (ARM Free Tier, 1 OCPU / 6GB 충분)
  - Image: Ubuntu 22.04
  - 공용 IP 할당, SSH 키 등록

- [ ] Security List에서 포트 개방
  - Oracle Cloud Security List: TCP 22, 80, 8000
  - Ubuntu iptables: 포트 8000 허용 + 저장

- [ ] VM에 Docker 설치

- [ ] 앱 클론 + 빌드 + 실행
  ```bash
  git clone https://github.com/JYKil/yeonsu-bot /opt/yeonsubot
  cd /opt/yeonsubot && mkdir -p data
  docker compose up -d --build
  ```

---

## Phase 6: 검증

- [ ] 로컬 `docker compose up` 후 `http://localhost:8000` 접속 확인
- [ ] 설정 입력 → [시작] → 로그 "로그인 중..." → "모니터링 중" 확인
- [ ] [중지] → 상태 "중지됨" 확인
- [ ] 실행 중 `/api/start` 재호출 → 409 응답 확인
- [ ] [Slack 테스트] → 웹훅 메시지 수신 확인
- [ ] 페이지 새로고침 → 상태 + 로그 버퍼 복원 확인
- [ ] WS 강제 끊김 → 3초 후 자동 재연결 확인
- [ ] Oracle Cloud VM에서 `http://<공용IP>:8000` 접속 확인
