# YeonsuBot 웹 전환 — 작업 목록

## 선행 작업

- [ ] **`/plan-design-review` 실행** — `DESIGN.md` (Apple 디자인 시스템)를 기준으로 디자인 리뷰 진행. 1슬롯 구조로 축소된 단일 패널 UI에 맞춰 탭 관련 토큰/컴포넌트 스펙 정리 필요.

---

## 확정된 설계 결정 (2026-04-13)

| 항목 | 결정 |
|------|------|
| 웹앱 인증 | 없음 — 로컬 전용, URL 알면 접근 |
| 실시간 로그 | WebSocket (FastAPI) |
| 예약 성공 후 | 자동 중지 + "예약완료" badge |
| 봇 슬롯 수 | 최대 3개, 기본 1개 |
| UI 레이아웃 | 탭 전환 + 설정 좌(40%) / 로그 우(60%) |
| 디자인 시스템 | DESIGN.md Apple 시스템 (SF Pro, #0071e3, #f5f5f7) |

---

## Phase 1: 핵심 로직 수정

- [ ] **`config.py`** — 슬롯별 설정 API
  - `base_dir`를 `os.environ.get("SETTINGS_DIR", ...)` 로 변경
  - `load(slot_id=0)` / `save(slot_id, settings)` — `settings_{slot_id}.json` 처리
  - `MAX_SLOTS = 3` 상수 추가

- [ ] **`checker.py`** — Linux headless 환경 대응
  - `_detect_browser_channel()`: 브라우저 못 찾으면 예외 대신 `None` 반환
  - `BrowserSession.start()`: `channel=None` 시 내장 Chromium 사용
  - launch 옵션에 `--no-sandbox`, `--disable-dev-shm-usage` 추가

- [ ] **`notifier.py`** — 슬롯 식별 추가
  - `send_booking_success()`, `send_booking_failure()`, `send_slack_notification()` 에
    `slot_label=None` 선택 파라미터 추가
  - `slot_label` 있으면 `[Slot N] ` 접두사를 메시지에 추가

---

## Phase 2: 백엔드 구현 (다중 슬롯)

- [ ] **`web_server.py`** 신규 생성 — FastAPI 앱
  - `SlotState` 데이터클래스 (scheduler, ws_clients, log_buffer, current_status)
  - `AppState` 클래스: `slots: list[SlotState]` (3개 고정)
  - `WebSocketLogHandler` (logging → 해당 슬롯 ws_clients 브로드캐스트)
  - lifespan 컨텍스트 (앱 종료 시 3개 슬롯 scheduler 정리)
  - REST 엔드포인트:
    - `GET /api/status` → 슬롯 3개 상태 배열
    - `GET /api/settings/{slot_id}` → 해당 슬롯 설정 (비밀번호 마스킹)
    - `POST /api/{slot_id}/start` → 설정 저장 + scheduler.start() (실행 중이면 409)
    - `POST /api/{slot_id}/stop` → 해당 슬롯 scheduler.stop()
    - `POST /api/{slot_id}/slack/test` → 해당 슬롯 Slack 테스트
  - WebSocket 엔드포인트: `WS /ws/{slot_id}` × 3 (재연결 시 log_buffer 즉시 전송)
  - scheduler 콜백 연결 (on_status_change, on_booking_result, on_error) — 슬롯별

- [ ] **`main.py`** 교체 — FastAPI 진입점
  - 기존 CustomTkinter 코드 제거
  - `uvicorn.run(app, host="0.0.0.0", port=8000)` 로 변경

---

## Phase 3: 프론트엔드 (탭 UI)

> **디자인 스펙**: `plan.md` → "프론트엔드 (탭 UI, Vanilla JS)" 섹션 참조.
> 승인된 목업: `~/.gstack/projects/JYKil-yeonsu-bot/designs/dashboard-variants-20260412/variant-final.png`
> (컬럼 순서 주의: 설정 왼쪽 40%, 로그 오른쪽 60%)

- [ ] **`templates/index.html`** 신규 생성 — 탭 방식 단일 페이지 UI
  - **레이아웃**: 다크 nav 바 + 탭 바 (최대 3개) + 설정 패널(좌 40%) / 로그 뷰어(우 60%)
  - **디자인 토큰**: `plan.md` 토큰 표 그대로 CSS 변수로 선언
    - `--color-bg: #f5f5f7`, `--color-accent: #0071e3`, `--color-surface-dark: #1d1d1f`
    - nav: `background: rgba(0,0,0,0.8)`, `backdrop-filter: saturate(180%) blur(20px)`
    - 활성 탭: `border-bottom: 2px solid #0071e3`
  - 탭: 계정 ID가 레이블 (예: `봇 1 — user@email.com`), 실행중이면 ● 표시
  - 설정 폼: 아이디, 비밀번호(보기 토글), 연수원 드롭다운, 체크인/아웃 날짜, 점검주기
    - 체크인 변경 시 체크아웃 자동 +1일
  - 상태 뱃지: 색 + 텍스트 동시 표시 (접근성), `role="status"`, `aria-live="polite"`
  - 버튼: 시작(Apple Blue), 중지(dark), 로그 지우기 — 최소 44px 터치 타겟
  - 로그 영역: 어두운 배경 `#1d1d1f`, 13px monospace, 자동 스크롤
  - 빈 상태 (봇 0개): "아직 봇이 없습니다 + 봇 추가 CTA" 중앙 표시
  - WS: 로드 시 `/ws/0~2` 3개 동시 연결, 끊김 시 3초 후 자동 재연결
  - 로드 시 `GET /api/status`로 3개 슬롯 상태 동기화
  - 예약 성공 시: 탭에 "예약완료" badge + 봇 자동 중지 반영
  - Slack 테스트 버튼 (선택, 설정 패널 하단)

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
  - `shm_size: "512mb"` (3개 슬롯 동시 Chromium 실행 필수)
  - `./data:/data` 볼륨 마운트

- [ ] **`.env.example`** 신규 생성

- [ ] **`gui.py`** 삭제

---

## Phase 5: Oracle Cloud 배포

- [ ] Oracle Cloud 계정 생성 및 Free Tier VM 생성
  - Shape: `VM.Standard.A1.Flex` (ARM, 2 OCPU / 12GB 권장)
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
- [ ] 슬롯 1 탭: 설정 입력 → [시작] → 로그 "로그인 중..." → "모니터링 중" 확인
- [ ] 슬롯 2 탭: 다른 계정으로 동시 실행 → 각 로그 독립 표시 확인
- [ ] 탭 상태 표시 (●) 실시간 반영 확인
- [ ] [중지] → 상태 "중지됨" 확인
- [ ] [Slack 테스트] → "[Slot 1] ..." 형식 메시지 수신 확인
- [ ] 페이지 새로고침 → 3개 슬롯 상태 + 로그 버퍼 복원 확인
- [ ] Oracle Cloud VM에서 `http://<공용IP>:8000` 접속 확인
