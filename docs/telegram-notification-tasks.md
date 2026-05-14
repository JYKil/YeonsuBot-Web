# 텔레그램 알림 기능 구현 태스크

기존 Slack 알림을 제거한 상태에서 텔레그램으로 전환하는 작업을 4개의 독립 태스크로 분리한다.
**순서대로 진행**할 것 (태스크 2·3은 태스크 1 완료 후 가능).

---

## 사전 정보

| 항목 | 값 |
|------|-----|
| 프로젝트 루트 | `YeonsuBot-Web/` |
| Telegram Bot API | `POST https://api.telegram.org/bot{token}/sendMessage` |
| 환경변수 | `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` |
| 현재 notifier.py | Slack 코드만 있음, 미사용 상태 |

---

## 태스크 1 — notifier.py: Slack → Telegram 전환

**대상 파일:** `notifier.py` (전면 교체)

**현재 상태:**
- Slack Incoming Webhook 기반 코드(`_post_webhook`, `send_slack_notification` 등) 4개 함수
- `SLACK_WEBHOOK_URL` 하드코딩 (보안 위험)
- 모두 미사용 상태

**구현 목표:**
- 기존 Slack 코드 전부 제거
- `os.getenv("TELEGRAM_BOT_TOKEN")`, `os.getenv("TELEGRAM_CHAT_ID")` 로 설정 읽기
- 토큰/Chat ID 미설정 시 경고 로그 후 `False` 반환 (앱 중단 없이 조용히 skip)
- 필요한 공개 함수 5개 구현:

| 함수 | 용도 | 메시지 예시 |
|------|------|------------|
| `notify_booking_success(username, facility, checkin, checkout)` | 예약 완료 | 🎉 예약 완료! 요청자: ... |
| `notify_worker_error(username, error_msg)` | 워커 비정상 종료 | ⚠️ 모니터링 중단: ... |
| `notify_session_expired(username)` | 세션 TTL 만료 | ⏰ 세션 만료로 중단: ... |
| `notify_heartbeat(username, elapsed_h, cycle)` | 3시간 경과 알림 | ✅ N시간째 모니터링 중 (N사이클) |
| `notify_test()` | 연결 테스트 | 테스트 메시지 |

---

### 한글 프롬프트

```
YeonsuBot-Web/notifier.py 파일을 Slack에서 텔레그램으로 전면 교체해줘.

현재 상태:
- Slack Incoming Webhook 기반 코드 (SLACK_WEBHOOK_URL 하드코딩, 미사용)

구현 규칙:
1. 기존 Slack 코드 전부 제거
2. 텔레그램 Bot API 사용: POST https://api.telegram.org/bot{token}/sendMessage
3. 환경변수에서 읽기: os.getenv("TELEGRAM_BOT_TOKEN"), os.getenv("TELEGRAM_CHAT_ID")
4. 토큰/Chat ID 미설정 시 경고 로그만 남기고 False 반환 (앱 중단 없이)
5. requests 라이브러리 사용 (이미 설치됨)

구현할 공개 함수:
- notify_booking_success(username: str, facility: str, checkin: str, checkout: str) -> bool
  메시지 예: "🎉 예약 완료!\n요청자: {username}\n연수원: {facility}\n체크인: {checkin}~{checkout}"
- notify_worker_error(username: str, error_msg: str) -> bool
  메시지 예: "⚠️ 모니터링 중단\n요청자: {username}\n사유: {error_msg}"
- notify_session_expired(username: str) -> bool
  메시지 예: "⏰ 세션 만료로 모니터링 중단\n요청자: {username}"
- notify_heartbeat(username: str, elapsed_h: int, cycle: int) -> bool
  메시지 예: "✅ 모니터링 중\n요청자: {username}\n경과: {elapsed_h}시간 ({cycle}사이클)"
- notify_test() -> bool
  메시지 예: "✅ 텔레그램 알림 테스트 메시지입니다. 연결 정상."

내부 공통 함수:
- _send(text: str) -> bool: 환경변수 읽고 Bot API POST, 실패 시 로그 후 False

모든 현재 시각은 KST(UTC+9)로 표기, datetime + timezone 사용.
코딩 스타일: 2칸 들여쓰기, 주석 한국어.
```

---

## 태스크 2 — scheduler.py/web_server.py: 예약 성공 + 워커 오류 + Heartbeat 알림

**대상 파일:** `scheduler.py`, `web_server.py`
**선행 조건:** 태스크 1 완료 후 진행

**현재 상태:**
- `_worker_loop()` (라인 93~133): 예외 발생 시 `on_error` 콜백만 호출
- `web_server.py`의 `SessionContext._on_error()`는 워커 오류를 WebSocket으로만 전달
- `_do_check_and_book()` (라인 135~207): 예약 성공 시 `라인 189~195`에서 로그·콜백만 호출
- `MonitorScheduler.__init__()` (라인 33~45): heartbeat 관련 상태 없음
- `_cycle_count` 이미 존재 (라인 38)

**구현 목표:**

### 2-A. 예약 성공 알림
`_do_check_and_book()` 내 `라인 189~195` (예약 성공 분기) 직후:
```python
notify_booking_success(self._log_username, self._yeonsu_gbn, ...)
```
`checkin`, `checkout`은 `self._target_dates`의 첫·마지막 날짜로 구성.

### 2-B. 워커 오류 알림
`scheduler.py`의 `_worker_loop()`에는 이미 `on_error` 콜백 호출이 있으므로 텔레그램 호출을 직접 추가하지 않는다.
대신 `web_server.py`의 `SessionContext._on_error()`에서 WebSocket 에러 브로드캐스트와 함께 텔레그램 알림을 보낸다.

```python
def _on_error(self, error: Exception) -> None:
    notifier.notify_worker_error(self.username, str(error))
    self._broadcast({"type": "error", "message": str(error)})
```

### 2-C. 3시간 Heartbeat
- `__init__`에 `self._last_heartbeat_at: datetime | None = None` 추가
- `_worker_loop()` 로그인 성공 직후 (`라인 100` 이후) 초기화:
  `self._last_heartbeat_at = datetime.now()`
- `_do_check_and_book()` 진입 시마다 경과 체크:
  ```python
  if self._last_heartbeat_at:
      elapsed = (datetime.now() - self._last_heartbeat_at).total_seconds() / 3600
      if elapsed >= 3:
          notify_heartbeat(self._log_username, int(elapsed), self._cycle_count)
          self._last_heartbeat_at = datetime.now()
  ```

---

### 한글 프롬프트

```
YeonsuBot-Web/scheduler.py에 텔레그램 알림 호출을 추가해줘.
그리고 YeonsuBot-Web/web_server.py의 워커 에러 콜백에 텔레그램 알림 호출을 추가해줘.
notifier.py는 이미 구현되어 있음 (notify_booking_success, notify_worker_error, notify_heartbeat 함수 존재).

추가할 내용 3가지:

[1] 예약 성공 알림 — _do_check_and_book() 메서드, 라인 189~195 부근
  success = True 분기 직후 (stop_event.set() 전)에 아래 추가:
  notify_booking_success(
      self._log_username,
      self._yeonsu_gbn,
      self._target_dates[0],           # checkin
      self._target_dates[-1],          # checkout
  )

[2] 워커 오류 알림 — web_server.py의 SessionContext._on_error()
  scheduler.py의 _worker_loop() except 블록에는 이미 on_error 콜백 호출이 있으므로 직접 텔레그램 호출을 추가하지 말 것.
  web_server.py의 SessionContext._on_error()에 아래 호출만 추가:

  notifier.notify_worker_error(self.username, str(error))

  최종 형태:
      def _on_error(self, error: Exception) -> None:
          notifier.notify_worker_error(self.username, str(error))
          self._broadcast({"type": "error", "message": str(error)})

[3] 3시간 Heartbeat — __init__ + _worker_loop + _do_check_and_book
  - __init__ (라인 33~45): self._last_heartbeat_at: datetime | None = None 추가
  - _worker_loop, 로그인 성공 직후 (라인 100 이후): self._last_heartbeat_at = datetime.now() 초기화
  - _do_check_and_book 진입부 (라인 140 cycle_count 증가 이후):
    if self._last_heartbeat_at is not None:
        elapsed = (datetime.now() - self._last_heartbeat_at).total_seconds() / 3600
        if elapsed >= 3:
            notify_heartbeat(self._log_username, int(elapsed), self._cycle_count)
            self._last_heartbeat_at = datetime.now()

주의:
- import는 파일 상단에 몰아서 추가 (함수 내부 inline import 사용 금지)
- datetime import가 없으면 추가
- 코드 스타일 유지: 2칸 들여쓰기
- scheduler.py의 except 블록 3개에 notify_worker_error를 반복해서 넣지 말 것
```

---

## 태스크 3 — auth.py: 세션 TTL 만료 알림

**대상 파일:** `auth.py`
**선행 조건:** 태스크 1 완료 후 진행

**현재 상태:**
- `resolve_session()` 라인 66~72: TTL 초과 시 `destroy_session()` 후 `None` 반환
- `notify_session_expired`를 import해도 circular import 없음 (`notifier.py`는 `requests·os·logging`만 사용)

**구현 목표:**
`resolve_session()` 내 TTL 만료 분기에 알림 추가:
```python
from notifier import notify_session_expired

if now - session.created_at > SESSION_TTL:
    notify_session_expired(session.username)  # ← 추가
    destroy_session(session_id)
    return None
```

---

### 한글 프롬프트

```
YeonsuBot-Web/auth.py의 resolve_session() 함수에 세션 만료 텔레그램 알림을 추가해줘.

현재 코드 (라인 66~72 부근):
    if now - session.created_at > SESSION_TTL:
        destroy_session(session_id)
        return None

변경 후:
    if now - session.created_at > SESSION_TTL:
        notify_session_expired(session.username)
        destroy_session(session_id)
        return None

주의사항:
- import는 파일 상단에 추가하는 것 권장 (circular import 없음 — notifier.py는 requests/os/logging만 사용)
- session.username으로 사용자명 접근 가능 (SessionInfo dataclass에 username 필드 있음)
- 다른 코드 건드리지 말 것
```

---

## 태스크 4 — .env.example: 환경변수 추가

**대상 파일:** `.env.example`
**선행 조건:** 없음 (독립 태스크)

**현재 상태:**
```
SETTINGS_DIR=/data
HOST=0.0.0.0
PORT=8000
HEADLESS=true
```

**구현 목표:** 텔레그램 환경변수 섹션 추가

---

### 한글 프롬프트

```
YeonsuBot-Web/.env.example 파일 하단에 텔레그램 알림 섹션을 추가해줘.

추가할 내용:
# 텔레그램 알림 설정 (없으면 알림 비활성화)
# Bot Token: @BotFather에서 발급
# Chat ID: 개인 채팅 또는 그룹 ID
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=

기존 내용은 수정하지 말 것.
```

---

## 진행 순서 요약

```
태스크 4  ← 독립, 언제든 가능
태스크 1  ← notifier.py 교체 (선행 필수)
    ↓
태스크 2  ← scheduler.py + web_server.py (태스크 1 후)
태스크 3  ← auth.py (태스크 1 후)
```
