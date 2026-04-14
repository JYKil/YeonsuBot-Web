# YeonsuBot 웹 전환 — 작업 목록

## 진행 상황 (2026-04-14)

| Phase | 상태 |
|---|---|
| 선행 — 디자인 리뷰 | ✅ 완료 (6.5 → 9.2/10) |
| Phase 1 — 핵심 로직 | ✅ 완료 |
| Phase 2 — FastAPI 백엔드 | ✅ 완료 |
| Phase 3 — 프론트엔드 | ✅ 완료 |
| Phase 4 — 패키지 & Docker | 🟡 requirements.txt 완료, Dockerfile/compose/env.example/gui.py 삭제 남음 |
| Phase 5 — Oracle Cloud 배포 | ⬜ 대기 |
| Phase 6 — 검증 | ⬜ 대기 |

---

## 선행 작업

- [x] **`/plan-design-review` 실행** — DESIGN.md Apple 시스템 기준. 디자인 토큰(Color/Typography/Spacing&Radius) 3개 표로 분리, 사용자 저널 + 상태 보조 라인 추가, flat 디자인 확정. 목업 `mockups/index.html` 생성.

---

## 확정된 설계 결정 (2026-04-14)

| 항목 | 결정 |
|------|------|
| 사용 주체 | 본인 1명 전용, 한 번에 한 세션 |
| 봇 슬롯 수 | **1개 고정** |
| 웹앱 인증 | 없음 — 로컬 전용, URL 알면 접근 |
| 실시간 로그 | WebSocket (FastAPI) |
| 예약 성공 후 | 자동 중지 + "예약완료" badge |
| UI 레이아웃 | 단일 패널 — 설정 좌(40%) / 로그 우(60%), flat (shadow 없음) |
| 동시 실행 방지 | `/api/start` 재호출 시 409 응답 |
| 디자인 시스템 | DESIGN.md Apple 시스템 (SF Pro, #0071e3, #f5f5f7) |
| 시작/중지 버튼 | 같은 자리 토글 |

---

## Phase 1: 핵심 로직 수정 ✅

- [x] **`config.py`** — Docker 볼륨 지원
  - `base_dir`를 `os.environ.get("SETTINGS_DIR", ...)` 로 변경
  - `SETTINGS_FILE = os.path.join(base_dir, "settings.json")`
  - `load()` / `save()` 시그니처 변경 없음
  - `os.makedirs(base_dir, exist_ok=True)` 로 SETTINGS_DIR 자동 생성

- [x] **`checker.py`** — Linux headless 환경 대응
  - `_detect_browser_channel()`: 브라우저 못 찾으면 예외 대신 `None` 반환
  - `BrowserSession.start()`: `channel=None` 시 내장 Chromium 사용
  - **시스템 Chrome 있을 때는 `--no-sandbox` 적용 안 함** (로컬 macOS/Windows 샌드박스 유지)
  - 내장 Chromium 사용 시에만 `--no-sandbox`, `--disable-dev-shm-usage` 적용

- [x] **`notifier.py`** — 변경 없음
- [x] **`scheduler.py`, `facilities.py`** — 변경 없음

---

## Phase 2: 백엔드 구현 ✅

- [x] **`web_server.py`** 신규 생성 — FastAPI 앱
  - `AppState` 클래스: `scheduler`, `ws_clients: set[WebSocket]`, `log_buffer: deque(maxlen=200)`, `current_status`, `last_check_at`, `last_result`, `loop`
  - `WebSocketLogHandler` (logging → `ws_clients` 브로드캐스트, `loop.call_soon_threadsafe()` 기반)
  - lifespan 컨텍스트 (앱 종료 시 `scheduler.stop()` + worker join(timeout=15))
  - REST 엔드포인트:
    - `GET /` → index.html
    - `GET /api/status` → `{running, status, last_check_at, next_check_at, target, last_result}`
    - `GET /api/settings` → 설정 로드 (비밀번호 마스킹 `********`) + facilities 목록
    - `POST /api/start` → 설정 저장 + `scheduler.start()` (이미 실행 중이면 409)
    - `POST /api/stop` → `scheduler.stop()`
    - `POST /api/slack/test` → Slack 웹훅 테스트
  - WebSocket 엔드포인트: `WS /ws` (연결 시 `log_buffer` + 상태 스냅샷 즉시 전송)
  - scheduler 콜백 연결 (on_status_change, on_booking_result, on_error, on_check_result)
  - 비밀번호 마스킹 재사용 로직 (빈 값/마스크 시 저장된 encoded 값 사용)

- [x] **`main.py`** 교체 — FastAPI 진입점
  - 기존 CustomTkinter 코드 제거
  - `uvicorn.run("web_server:app", host, port)` 로 변경
  - `HOST`/`PORT` 환경변수 지원

---

## Phase 3: 프론트엔드 ✅

- [x] **`templates/index.html`** 신규 생성 — 단일 페이지 UI
  - **레이아웃**: 다크 nav 바 + 설정 패널(좌 40%) / 로그 뷰어(우 60%) 2열, flat 디자인
  - **정보 계층**: 상태+액션 → 폼 → 로그 (액션 버튼을 폼 위로 배치)
  - **디자인 토큰**: Color/Typography/Spacing&Radius CSS 변수로 선언, DESIGN.md 행 매핑
  - **상태 뱃지 + 보조 라인**: `마지막 확인: 09:23 · 다음: 09:25 · 대상: 신구로 5/1~5/2`
  - **시작/중지 토글**: 실행 상태에 따라 START 또는 STOP 하나만 노출
  - **설정 폼**: 아이디, 비밀번호 + 표시 토글(aria-pressed), 연수원 드롭다운, 체크인/아웃, 점검주기
    - 체크인 변경 시 체크아웃 자동 +1일
    - `autocomplete="username"` / `"current-password"`
  - **인터랙션 상태**: 빈 상태, 시작 LOADING, 409 토스트, WS 끊김 배너, Slack 테스트 토스트
  - **로그 뷰어**: SF Mono 13px, 컬러 코딩(성공/경고/오류), 자동 스크롤
    - 사용자가 위로 스크롤 시 autoscroll pause + `↓ 새 로그 N건` 버튼
  - **WS**: 연결 시 버퍼 재수신, 끊김 시 3초 후 자동 재연결
  - **예약 성공 시**: "예약완료" 뱃지 + 자동 중지 반영 (statusLabel/statusBadge 형제 hidden 토글로 idempotent 렌더)
  - **접근성**: focus ring 2px `#0071e3`, aria-live, 44px 터치 타겟, `prefers-reduced-motion`
  - **반응형**: 1070px↓ 패널 폭 축소, 640px↓ 세로 스택 (로그 min-height 240px)
  - Slack 테스트 버튼 (설정 패널 하단)

---

## Phase 4: 패키지 및 Docker

- [x] **`requirements.txt`** 업데이트
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
  git clone https://github.com/JYKil/YeonsuBot-Web /opt/yeonsubot
  cd /opt/yeonsubot && mkdir -p data
  docker compose up -d --build
  ```

---

## Phase 6: 검증

- [ ] 로컬 `uv run python main.py` 후 `http://localhost:8000` 접속 확인
- [ ] 첫 로드: 빈 상태 안내 표시 확인
- [ ] 설정 입력 → [시작] → 버튼 spinner → 상태 "모니터링 중" + 보조 라인 표시 확인
- [ ] [중지] → 상태 "중지", 버튼 START 로 토글 확인
- [ ] 실행 중 `/api/start` 재호출 → 409 + 인라인 토스트 확인
- [ ] [Slack 테스트] → 성공 토스트 + 웹훅 메시지 수신 확인
- [ ] 페이지 새로고침 → 상태 + 로그 버퍼 + 보조 라인 복원 확인
- [ ] WS 강제 끊김 → 인라인 배너 + 3초 후 자동 재연결 확인
- [ ] 로그 위로 스크롤 → autoscroll pause + "↓ 새 로그 N건" 버튼 확인
- [ ] 예약 성공 시뮬레이션 → "예약완료" 뱃지 + 자동 중지 → 재시작 시 뱃지 복귀 확인
- [ ] 키보드 Tab → focus ring + 의도된 순서 확인
- [ ] 모바일 viewport (375px) → 세로 스택 + 로그 영역 240px 이상 확인
- [ ] Docker: `docker compose up` 후 동일 절차 반복
- [ ] Oracle Cloud VM에서 `http://<공용IP>:8000` 접속 확인
