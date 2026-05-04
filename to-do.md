# YeonsuBot 웹 전환 — 작업 목록

## 진행 상황

| Phase | 상태 |
|---|---|
| 선행 — 디자인 리뷰 | ✅ 완료 (6.5 → 9.2/10) |
| Phase 1 — 핵심 로직 | ✅ 완료 |
| Phase 2 — FastAPI 백엔드 | ✅ 완료 |
| Phase 3 — 프론트엔드 | ✅ 완료 |
| Phase 4 — 패키지 & Docker | ✅ 완료 |
| Phase 5 — Beelink 배포 (GitLab + Jenkins CI/CD) | ✅ 완료 (http://192.168.75.205:3000 운영 중) |
| Phase 6 — 로컬 검증 | ✅ 완료 |
| Phase 7 — 운영 버그 수정 | ✅ 완료 |
| Phase 8 — 텔레그램 알림 전환 | 🔲 예정 |

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

## Phase 7: 운영 버그 수정 ✅

전체 증상/원인/수정 상세는 `BUGFIX_LOG.md`.

### 예약 플로우 버그

- [x] 객실 목록 로드 실패 — URL 이동 후 `search()` 명시적 호출
- [x] 객실 목록을 날짜 포함 URL로 직접 이동
- [x] 달력 초기화 대기 — `showCalendar` 정의 대기 + 버튼 enabled 대기
- [x] 달력 가용 날짜 판정 — `td.onclick` 핸들러도 확인
- [x] 객실선택 radio button — name 속성으로 탐색
- [x] 객실선택 대기 시간 10s → 20s (총 40s)
- [x] 객실 목록 로드 판정 — 자동 로드 확인으로 search() 중복 호출 방지
- [x] 결과 판정 순서 — dialog 체크를 네비게이션보다 먼저
- [x] 연수원 선택 — `change` 이벤트 dispatch로 서버 세션 갱신
- [x] 객실 목록 페이지 폼 요소 대기 — `#check_in_day` attach 대기

### 기타

- [x] stop 후 상태 덮어쓰기 방지 + 대상 표시 개선
- [x] Slack Webhook URL 갱신
- [x] page.evaluate 인자 리스트로 전달

### 남은 관찰 포인트

- [ ] 연속 장시간 운영 시 브라우저 재시작(50회) 동작 검증
- [ ] 실제 빈방 발생 시 전체 예약 플로우 E2E 검증
- [ ] 여수히든베이/여수베네치아연수원 예약 불가 수정 검증

---

## Phase 8: 텔레그램 알림 전환 🔲

Slack Incoming Webhook → Telegram Bot API로 교체.

### 사전 준비

- [ ] BotFather에서 봇 생성 → `BOT_TOKEN` 발급
- [ ] 봇과 대화 후 `chat_id` 확인 (`https://api.telegram.org/bot<TOKEN>/getUpdates`)

### 코드 변경

- [ ] **`notifier.py`** — Telegram Bot API로 교체
  - `requests.post(f"https://api.telegram.org/bot{token}/sendMessage", json={chat_id, text})` 방식
  - 빈방 발견 / 예약 성공·실패 / 테스트 메시지 포맷 유지
  - Slack webhook URL 파라미터 → `telegram_token` + `telegram_chat_id`

- [ ] **`config.py`** — 설정 키 변경
  - `slack_webhook_url` → `telegram_token`, `telegram_chat_id`
  - `DEFAULTS` 업데이트

- [ ] **`web_server.py`** — 테스트 엔드포인트 업데이트
  - `POST /api/slack/test` → `POST /api/telegram/test`
  - 설정 응답에서 `slack_webhook_url` 필드 제거

- [ ] **`templates/index.html`** — 설정 폼 업데이트
  - Slack Webhook URL 입력 필드 → 텔레그램 봇 토큰 + Chat ID 입력 필드
  - "Slack 테스트" 버튼 → "텔레그램 테스트"

### 검증

- [ ] 테스트 메시지 전송 → 텔레그램 수신 확인
- [ ] 봇 시작 시 알림 동작 확인
- [ ] `docker compose up --build` 후 재배포 확인
