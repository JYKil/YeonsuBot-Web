# Admin 현황판 지표 개편 계획

관리자 페이지의 목적을 "누가 로그인했는가"보다 "각 계정의 봇이 실제로 돌고 있는가" 확인으로 좁힌다. 기존 `세션 수`, `연결 창 수`는 운영 판단에 혼동을 주므로 기본 표에서 제거하거나 디버그 영역으로 내린다.

---

## 결론

기본 표 컬럼은 아래 순서로 개편한다.

| 컬럼 | 의미 |
|------|------|
| 계정 | 사용자 계정명 |
| 최근 로그인 | 해당 계정의 가장 최근 로그인 시각 |
| 실행 여부 | scheduler가 현재 실행 중인지 |
| 현재 상태 | 로그인 중, 모니터링 중, 예약 시도 중, 중지 등 |
| 모니터링 횟수 | START 이후 빈방 확인 사이클 누적 횟수 |

`모니터링 시간`보다 `모니터링 횟수`를 우선한다.

이유:
- 알림 정책을 만들 때 `100회마다 알림`처럼 명확한 트리거로 쓰기 쉽다.
- 체크 간격이 사용자 설정값이므로 단순 경과 시간보다 실제 작업량을 더 정확히 보여준다.
- 일시적인 체크 실패나 긴 interval 설정에서도 "몇 번 실제 확인했는지"가 운영상 더 중요하다.

다만 사용자가 체감하기 쉽게 `모니터링 시간`도 API에는 함께 내려주고, UI에서는 필요 시 `모니터링 횟수` 옆 보조 텍스트나 툴팁으로 표시할 수 있게 설계한다.

예:

```text
37회
```

추후 확장:

```text
37회 / 1시간 12분
```

---

## 현재 문제

기존 Admin 표:

| 컬럼 | 문제 |
|------|------|
| 세션 수 | 로그인 토큰 수라서 실제 봇 실행 여부와 직접 관련이 낮음 |
| 최초 로그인 | 여러 세션 중 가장 오래된 토큰 기준이라 운영 판단에 애매함 |
| 연결 창 수 | WebSocket 연결 수라서 앱 화면을 닫아도 봇 실행과 무관하게 0이 될 수 있음 |

운영자가 실제로 알고 싶은 것은 아래다.

- 어떤 계정이 사용 중인가
- 봇이 실행 중인가
- 지금 어떤 단계인가
- START 이후 실제로 몇 번 확인했는가
- 마지막으로 로그인한 시각이 언제인가

---

## 데이터 정의

### 최근 로그인

`auth._sessions`에서 username별로 가장 늦은 `created_at`을 사용한다.

현재 `admin_session_snapshot()`은 `first_created_at`, `last_seen_at`, `session_count`를 반환한다. 개편 시 아래 필드를 추가한다.

| 필드 | 의미 |
|------|------|
| `latest_created_at` | 해당 username의 가장 최근 세션 생성 시각 |

UI 컬럼명은 `최근 로그인`으로 표시한다.

주의:
- `last_seen_at`은 API 호출이나 WebSocket 인증 때 갱신되는 "활동 시각"이다.
- 로그인 시각과 활동 시각은 의미가 다르므로 `최근 로그인`에는 `created_at` 기준을 써야 한다.

### 실행 여부

기존 `ctx.scheduler.is_running`을 그대로 사용한다.

응답 필드:

```json
"running": true
```

UI 표시:

```text
실행 중
중지
```

### 현재 상태

기존 `ctx.current_status`를 그대로 사용한다.

예:

```text
로그인 중...
모니터링 중
예약 시도 중
중지
중지됨
```

### 모니터링 횟수

START 클릭 후 현재 실행 세션에서 수행한 체크 사이클 수다.

현재 `scheduler.py`에는 `_cycle_count`가 이미 있고, `_do_check_and_book()` 진입 시 증가한다.

개편 시 읽기 전용 property를 추가한다.

```python
@property
def cycle_count(self) -> int:
    return self._cycle_count
```

Admin API는 `ctx.scheduler.cycle_count`를 `monitoring_count`로 반환한다.

정의:
- START 직후 첫 체크가 시작되면 1
- 체크 실패도 "확인 시도"로 보아 1회에 포함
- STOP 후 값은 마지막 실행의 누적 횟수로 남길지, 0으로 보일지 정책 결정 필요

권장 정책:
- 실행 중이면 현재 누적 횟수 표시
- 중지 상태면 `-` 표시
- 예약 성공이나 사용자가 STOP한 뒤 과거 횟수는 API에는 남겨도 UI 기본 표에서는 숨김

### 모니터링 시간

START 시각부터 현재까지의 경과 시간이다.

모니터링 횟수보다 우선순위는 낮지만, API 필드로 함께 제공할 수 있다.

필요 필드:

| 위치 | 필드 | 의미 |
|------|------|------|
| `SessionContext` | `monitoring_started_at` | START가 성공적으로 접수된 시각 |
| Admin API | `monitoring_started_at` | KST 문자열 |
| Admin API | `monitoring_elapsed_seconds` | 실행 중일 때 현재까지의 초 |

주의:
- "로그인 후 START 클릭 후 빈방이 없어서 모니터링 중"인 시간을 보려면 START 요청 시각보다 실제 `모니터링 중` 상태 진입 시각이 더 정확하다.
- 하지만 로그인 성공 후 바로 첫 체크에 들어가므로, 구현 단순성과 운영상 충분성을 고려하면 START 요청 시각을 기준으로 잡아도 된다.
- 더 정확히 하려면 `_on_status_change("모니터링 중")`이 처음 호출된 시각을 `monitoring_started_at`으로 기록한다.

권장 정책:
- 정확한 의미는 "모니터링 상태 진입 후 경과 시간"으로 정의한다.
- `SessionContext._on_status_change()`에서 상태가 처음 `모니터링 중`으로 바뀌는 순간을 기록한다.
- STOP, 예약 성공, 로그인 실패, 브라우저 오류 시 `monitoring_started_at`은 `None`으로 초기화한다.

---

## API 변경 계획

대상: `GET /api/admin/sessions`

기존 주요 응답:

```json
{
  "username": "user1",
  "session_count": 2,
  "first_created_at": "2026-05-15 10:00:00",
  "last_seen_at": "2026-05-15 10:30:00",
  "running": true,
  "status": "모니터링 중",
  "last_check_at": "10:29:52",
  "ws_client_count": 0
}
```

개편 응답:

```json
{
  "username": "user1",
  "latest_login_at": "2026-05-15 10:20:00",
  "running": true,
  "status": "모니터링 중",
  "monitoring_count": 37,
  "monitoring_started_at": "2026-05-15 10:21:03",
  "monitoring_elapsed_seconds": 4320
}
```

디버그용으로 기존 필드를 당장 제거하지 않고 유지할 수 있다.

```json
{
  "debug": {
    "session_count": 2,
    "last_seen_at": "2026-05-15 10:30:00",
    "ws_client_count": 0
  }
}
```

권장:
- 1차 구현에서는 기존 필드를 응답에 남겨 하위 호환성을 유지한다.
- Admin UI에서는 새 컬럼만 표시한다.

---

## UI 변경 계획

대상: `templates/admin.html`

표 헤더를 아래로 변경한다.

```text
계정 | 최근 로그인 | 실행 여부 | 현재 상태 | 모니터링 횟수
```

표시 규칙:

| 상태 | 모니터링 횟수 표시 |
|------|--------------------|
| 실행 중 + 모니터링 중 | `N회` |
| 실행 중 + 로그인 중 | `-` 또는 `0회` |
| 예약 시도 중 | 현재 누적 `N회` |
| 중지 | `-` |

선택 확장:
- `monitoring_elapsed_seconds`가 있으면 `N회 / 1시간 12분` 형식으로 표시 가능
- 기본 구현은 `N회`만 표시해서 화면을 단순하게 유지

---

## 구현 태스크

### 태스크 1 - auth.py: 최근 로그인 필드 추가

`admin_session_snapshot()`에 username별 가장 늦은 `created_at`을 계산하는 `latest_created_at` 필드를 추가한다.

주의:
- 기존 `first_created_at`은 하위 호환을 위해 남긴다.
- token/session_id는 계속 반환하지 않는다.

### 태스크 2 - scheduler.py: 모니터링 횟수 property 추가

`MonitorScheduler`에 읽기 전용 `cycle_count` property를 추가한다.

주의:
- `_cycle_count` 증가 위치는 현재처럼 `_do_check_and_book()` 진입 시 유지한다.
- start 시 0으로 리셋되는 기존 동작을 유지한다.

### 태스크 3 - web_server.py: 모니터링 시작 시각 추적

`SessionContext`에 아래 필드를 추가한다.

```python
self.monitoring_started_at: datetime | None = None
```

상태 변경 처리:
- 상태가 처음 `모니터링 중`이 되고 scheduler가 실행 중이면 현재 시각으로 설정
- `중지`, `중지됨`, 예약 성공, 로그인 실패, 브라우저 오류 시 `None`으로 초기화

### 태스크 4 - web_server.py: Admin API 응답 개편

`/api/admin/sessions` 응답에 아래 필드를 추가한다.

| 필드 | 값 |
|------|----|
| `latest_login_at` | `latest_created_at` KST 포맷 |
| `monitoring_count` | `ctx.scheduler.cycle_count` |
| `monitoring_started_at` | KST 포맷 |
| `monitoring_elapsed_seconds` | 실행 중이고 시작 시각이 있으면 현재 - 시작 시각 |

기존 `session_count`, `first_created_at`, `last_seen_at`, `ws_client_count`는 응답에는 남기되 UI에서 제거한다.

### 태스크 5 - templates/admin.html: 표 컬럼 변경

표 헤더와 렌더링 로직을 새 컬럼으로 변경한다.

제거:
- 세션 수
- 최초 로그인
- 마지막 활동
- 마지막 체크
- 연결 창 수

추가/변경:
- 최근 로그인
- 모니터링 횟수

---

## 알림 연계 계획

향후 Telegram 알림을 붙일 때 `monitoring_count`를 기준으로 삼는다.

예:

```python
if cycle_count > 0 and cycle_count % 100 == 0:
    notify_monitoring_progress(username, cycle_count)
```

주의:
- 체크 실패도 횟수에 포함할지 정책을 유지해야 한다.
- 예약 가능 날짜 일부 불일치도 "확인 1회"로 본다.
- 알림 중복 방지를 위해 마지막 알림 횟수 `last_notified_cycle_count`를 사용자 context나 notifier 상태에 저장해야 한다.

---

## 검증 계획

1. admin 로그인 후 표 컬럼이 `계정/최근 로그인/실행 여부/현재 상태/모니터링 횟수`로 보이는지 확인
2. 사용자 로그인 직후 `최근 로그인`이 갱신되는지 확인
3. START 전에는 `실행 여부=중지`, `모니터링 횟수=-`인지 확인
4. START 후 첫 체크 진입 시 `모니터링 횟수=1회`가 되는지 확인
5. interval이 지나 다음 체크가 돌면 횟수가 2회 이상 증가하는지 확인
6. STOP 후 `실행 여부=중지`, `모니터링 횟수=-`로 보이는지 확인
7. 브라우저 창을 닫아도 실행 중이면 횟수가 계속 증가하는지 확인
8. 기존 `/api/admin/sessions` 호출이 500 없이 JSON을 반환하는지 확인

---

## 보류 결정

아래는 구현 직전 최종 결정이 필요하다.

| 항목 | 권장안 |
|------|--------|
| 기본 컬럼명 | `모니터링 횟수` |
| 시간 표시 | 1차 구현에서는 숨김, API 필드만 준비 |
| 중지 상태 횟수 | UI에서는 `-` |
| 체크 실패 횟수 포함 | 포함 |
| 기존 debug 필드 제거 | 제거하지 않고 응답에 유지 |

---

## 구현 Phase 및 프롬프트

아래 phase는 순서대로 진행한다. 단, Phase 1A와 Phase 1B는 서로 파일이 다르고 의존성이 없으므로 병렬 진행 가능하다.

### 전체 처리 순서

| 순서 | Phase | 대상 | 병렬 가능 여부 | 비고 |
|------|-------|------|----------------|------|
| 1 | Phase 1A | `auth.py` | Phase 1B와 병렬 가능 | 최근 로그인 필드 추가 |
| 1 | Phase 1B | `scheduler.py` | Phase 1A와 병렬 가능 | 모니터링 횟수 property 추가 |
| 2 | Phase 2 | `web_server.py` | Phase 1 완료 후 진행 | API가 Phase 1A/1B 필드를 사용 |
| 3 | Phase 3 | `templates/admin.html` | Phase 2 완료 후 진행 | 새 API 응답 필드 표시 |
| 4 | Phase 4 | 검증 | Phase 1~3 완료 후 진행 | API/UI 동작 확인 |

병렬화 기준:
- `auth.py`와 `scheduler.py`는 서로 독립적이므로 동시에 작업 가능
- `web_server.py`는 `latest_created_at`, `cycle_count`를 참조하므로 Phase 1 이후 진행
- `templates/admin.html`은 Admin API 응답 형태가 정해진 뒤 진행
- 검증은 모든 변경 후 마지막에 진행

---

### Phase 1A - auth.py: 최근 로그인 필드 추가

**목표:** Admin 스냅샷에서 username별 가장 최근 로그인 시각을 제공한다.

**대상 파일:** `auth.py`

**병렬 가능:** Phase 1B와 병렬 가능

**선행 조건:** 없음

**프롬프트:**

```text
YeonsuBot-Web/auth.py의 admin_session_snapshot()에 최근 로그인 필드를 추가해줘.
Add a recent login field to admin_session_snapshot() in YeonsuBot-Web/auth.py.

현재 상태:
Current state:
- SessionInfo에는 username, created_at, last_seen_at 필드가 있음
- SessionInfo has username, created_at, and last_seen_at fields.
- admin_session_snapshot()은 username 기준으로 session_count, first_created_at, last_seen_at을 집계함
- admin_session_snapshot() aggregates session_count, first_created_at, and last_seen_at by username.

구현할 내용:
Implementation tasks:
1. username별 가장 늦은 created_at을 latest_created_at으로 계산
1. Calculate the latest created_at per username as latest_created_at.
2. 새 username 항목 생성 시 latest_created_at = session.created_at 추가
2. When creating a new username entry, add latest_created_at = session.created_at.
3. 같은 username의 추가 세션을 처리할 때 session.created_at이 더 늦으면 latest_created_at 갱신
3. When processing another session for the same username, update latest_created_at if session.created_at is later.
4. 기존 first_created_at, last_seen_at, session_count 동작은 유지
4. Keep the existing first_created_at, last_seen_at, and session_count behavior.
5. 반환 정렬은 기존처럼 last_seen_at 내림차순 유지
5. Keep the return sort order as last_seen_at descending, same as before.

주의:
Notes:
- session_id/token 값은 반환하지 말 것
- Do not return session_id/token values.
- datetime은 문자열로 변환하지 말고 timezone-aware datetime 객체 그대로 반환
- Do not convert datetime values to strings; return timezone-aware datetime objects as-is.
- 기존 current_user(), resolve_session(), destroy_session() 동작을 바꾸지 말 것
- Do not change the existing behavior of current_user(), resolve_session(), or destroy_session().
```

**완료 기준:**
- `admin_session_snapshot()` 반환 dict에 `latest_created_at`이 포함된다.
- 같은 계정으로 여러 세션이 있을 때 가장 최근 `created_at`이 선택된다.

---

### Phase 1B - scheduler.py: 모니터링 횟수 property 추가

**목표:** Admin API가 현재 실행 세션의 체크 사이클 수를 읽을 수 있게 한다.

**대상 파일:** `scheduler.py`

**병렬 가능:** Phase 1A와 병렬 가능

**선행 조건:** 없음

**프롬프트:**

```text
YeonsuBot-Web/scheduler.py의 MonitorScheduler에 모니터링 횟수 조회용 property를 추가해줘.
Add a property for reading the monitoring count to MonitorScheduler in YeonsuBot-Web/scheduler.py.

현재 상태:
Current state:
- MonitorScheduler.__init__()에 self._cycle_count = 0 이 있음
- MonitorScheduler.__init__() already has self._cycle_count = 0.
- start() 호출 시 self._cycle_count = 0 으로 리셋됨
- start() resets self._cycle_count to 0.
- _do_check_and_book() 진입 시 self._cycle_count += 1 로 증가함
- _do_check_and_book() increments self._cycle_count by 1 when it starts.

구현할 내용:
Implementation tasks:
1. MonitorScheduler 클래스에 아래 읽기 전용 property 추가:
1. Add the following read-only property to the MonitorScheduler class:

   @property
   def cycle_count(self) -> int:
       return self._cycle_count

2. _cycle_count 증가 위치와 리셋 동작은 바꾸지 말 것
2. Do not change where _cycle_count increments or how it resets.
3. stop(), start(), _worker_loop()의 기존 동작은 바꾸지 말 것
3. Do not change the existing behavior of stop(), start(), or _worker_loop().

주의:
Notes:
- 이번 phase에서는 알림 로직을 추가하지 말 것
- Do not add notification logic in this phase.
- 체크 실패도 기존 구조상 1회로 카운트되므로 이 정책을 유지할 것
- A failed check is counted as one attempt in the existing structure; keep that policy.
```

**완료 기준:**
- `ctx.scheduler.cycle_count`로 현재 카운트를 읽을 수 있다.
- START 시 0으로 리셋되고 첫 체크 진입 시 1이 된다.

---

### Phase 2 - web_server.py: Admin API 응답 개편

**목표:** Admin API가 새 UI에 필요한 필드를 내려주도록 한다.

**대상 파일:** `web_server.py`

**병렬 가능:** 불가

**선행 조건:** Phase 1A, Phase 1B 완료

**프롬프트:**

```text
YeonsuBot-Web/web_server.py의 admin 세션 API를 새 현황판 지표에 맞게 확장해줘.
Extend the admin sessions API in YeonsuBot-Web/web_server.py for the new dashboard metrics.

선행 조건:
Prerequisites:
- auth.admin_session_snapshot()은 latest_created_at을 반환함
- auth.admin_session_snapshot() returns latest_created_at.
- MonitorScheduler에는 cycle_count property가 있음
- MonitorScheduler has a cycle_count property.

구현할 내용:
Implementation tasks:
1. SessionContext.__init__()에 monitoring_started_at 필드 추가:
1. Add the monitoring_started_at field to SessionContext.__init__():

   self.monitoring_started_at: datetime | None = None

2. SessionContext._on_status_change()에서 모니터링 시작 시각을 관리:
2. Manage the monitoring start time in SessionContext._on_status_change():
   - status가 "모니터링 중"이고 scheduler가 실행 중이며 monitoring_started_at이 None이면 현재 KST datetime으로 설정
   - If status is "모니터링 중", the scheduler is running, and monitoring_started_at is None, set it to the current KST datetime.
   - status가 "중지" 또는 "중지됨"이면 monitoring_started_at을 None으로 초기화
   - If status is "중지" or "중지됨", reset monitoring_started_at to None.

3. SessionContext._on_booking_result()에서 예약 성공 또는 로그인/브라우저 오류 결과를 받으면 monitoring_started_at을 None으로 초기화
3. In SessionContext._on_booking_result(), reset monitoring_started_at to None when the result is booking success or a login/browser error.
   - SUCCESS
   - LOGIN_ERROR
   - BROWSER_ERROR

4. /api/admin/sessions 응답 row에 아래 필드 추가:
4. Add the following fields to each /api/admin/sessions response row:
   - latest_login_at: session["latest_created_at"]을 _format_kst_datetime()으로 포맷
   - latest_login_at: format session["latest_created_at"] with _format_kst_datetime().
   - monitoring_count: ctx.scheduler.cycle_count if ctx else 0
   - monitoring_count: ctx.scheduler.cycle_count if ctx else 0.
   - monitoring_started_at: ctx.monitoring_started_at을 _format_kst_datetime()으로 포맷
   - monitoring_started_at: format ctx.monitoring_started_at with _format_kst_datetime().
   - monitoring_elapsed_seconds: ctx가 있고 running이고 monitoring_started_at이 있으면 현재 시각 - 시작 시각 초 단위, 아니면 None
   - monitoring_elapsed_seconds: if ctx exists, running is true, and monitoring_started_at exists, return current time minus start time in seconds; otherwise return None.

5. 기존 필드 session_count, first_created_at, last_seen_at, ws_client_count는 응답에서 제거하지 말고 유지
5. Keep the existing session_count, first_created_at, last_seen_at, and ws_client_count fields in the response.
6. rows 정렬은 latest_login_at 또는 last_seen_at 기준으로 안정적으로 유지
6. Keep row sorting stable based on latest_login_at or last_seen_at.

주의:
Notes:
- templates/admin.html은 이 phase에서 수정하지 말 것
- Do not modify templates/admin.html in this phase.
- 기존 사용자 페이지 API, WebSocket 동작을 바꾸지 말 것
- Do not change the existing user page API or WebSocket behavior.
- datetime timezone 처리를 기존 _KST, _format_kst_datetime() 흐름과 맞출 것
- Keep datetime timezone handling aligned with the existing _KST and _format_kst_datetime() flow.
```

**완료 기준:**
- `/api/admin/sessions` JSON에 새 필드 4개가 포함된다.
- 기존 Admin UI가 깨지지 않도록 기존 필드는 유지된다.
- 실행 중이 아니면 `monitoring_elapsed_seconds`는 `null`이다.

---

### Phase 3 - templates/admin.html: 표 컬럼 변경

**목표:** Admin 표를 운영에 필요한 핵심 지표 중심으로 단순화한다.

**대상 파일:** `templates/admin.html`

**병렬 가능:** 불가

**선행 조건:** Phase 2 완료

**프롬프트:**

```text
YeonsuBot-Web/templates/admin.html의 Admin 현황판 표 컬럼을 새 지표로 변경해줘.
Change the Admin dashboard table columns in YeonsuBot-Web/templates/admin.html to the new metrics.

선행 조건:
Prerequisites:
- /api/admin/sessions 응답에 latest_login_at, monitoring_count, monitoring_started_at, monitoring_elapsed_seconds가 포함됨
- The /api/admin/sessions response includes latest_login_at, monitoring_count, monitoring_started_at, and monitoring_elapsed_seconds.
- 기존 session_count, first_created_at, last_seen_at, ws_client_count는 응답에 남아 있지만 UI 기본 표에서는 사용하지 않음
- The existing session_count, first_created_at, last_seen_at, and ws_client_count fields remain in the response but are not used in the default UI table.

구현할 내용:
Implementation tasks:
1. 표 헤더를 아래 5개 컬럼으로 변경:
1. Change the table header to the following five columns:
   - 계정
   - Account
   - 최근 로그인
   - Recent login
   - 실행 여부
   - Running status
   - 현재 상태
   - Current status
   - 모니터링 횟수
   - Monitoring count

2. renderRows()에서 각 row 표시를 아래로 변경:
2. Change each row in renderRows() to display:
   - username
   - latest_login_at
   - running pill
   - status
   - monitoring_count 표시
   - monitoring_count display

3. 모니터링 횟수 표시 규칙:
3. Monitoring count display rules:
   - session.running이 true이고 session.monitoring_count > 0 이면 "{N}회"
   - If session.running is true and session.monitoring_count > 0, show "{N}회".
   - 그 외에는 "-"
   - Otherwise, show "-".

4. 기존 세션 수, 최초 로그인, 마지막 활동, 마지막 체크, 연결 창 수 컬럼은 UI에서 제거
4. Remove the existing session count, first login, last activity, last check, and connected windows columns from the UI.
5. 비밀번호 입력, 새로고침, 인증 실패 처리, 자동 refresh 동작은 유지
5. Keep password entry, refresh, authentication failure handling, and automatic refresh behavior.

주의:
Notes:
- 이번 phase에서는 모니터링 시간을 표시하지 말 것
- Do not display monitoring time in this phase.
- CSS는 필요한 최소 범위만 수정
- Keep CSS changes to the minimum necessary scope.
- admin 비밀번호를 storage에 저장하지 않는 기존 정책을 유지
- Keep the existing policy of not storing the admin password in browser storage.
```

**완료 기준:**
- Admin 표에 `계정/최근 로그인/실행 여부/현재 상태/모니터링 횟수`만 보인다.
- 실행 중이며 체크가 1회 이상 돌면 `N회`로 표시된다.
- 중지 상태는 `-`로 표시된다.

---

### Phase 4 - 검증

**목표:** API와 UI가 새 지표 기준으로 정상 동작하는지 확인한다.

**대상:** 전체 변경

**병렬 가능:** 불가

**선행 조건:** Phase 1~3 완료

**프롬프트:**

```text
YeonsuBot-Web Admin 현황판 지표 개편을 검증해줘.
Verify the YeonsuBot-Web Admin dashboard metrics redesign.

검증할 내용:
Verification items:
1. 정적 검사 또는 테스트 가능한 범위에서 문법 오류가 없는지 확인
1. Check for syntax errors using static checks or any testable scope.
2. ADMIN_PASSWORD를 설정한 상태로 서버를 실행
2. Run the server with ADMIN_PASSWORD set.
3. /api/admin/sessions에 올바른 X-YeonsuBot-Admin-Password를 보내면 JSON이 반환되는지 확인
3. Confirm that /api/admin/sessions returns JSON when called with the correct X-YeonsuBot-Admin-Password.
4. JSON row에 latest_login_at, running, status, monitoring_count, monitoring_started_at, monitoring_elapsed_seconds가 포함되는지 확인
4. Confirm that each JSON row includes latest_login_at, running, status, monitoring_count, monitoring_started_at, and monitoring_elapsed_seconds.
5. /admin 페이지 표 헤더가 계정/최근 로그인/실행 여부/현재 상태/모니터링 횟수로 표시되는지 확인
5. Confirm that the /admin table header shows Account / Recent login / Running status / Current status / Monitoring count.
6. START 전에는 모니터링 횟수가 "-"로 표시되는지 확인
6. Confirm that the monitoring count is shown as "-" before START.
7. START 후 첫 체크가 시작되면 monitoring_count가 1 이상으로 증가하는지 확인
7. Confirm that monitoring_count increases to 1 or more after the first check starts after START.
8. STOP 후 실행 여부가 중지로 바뀌고 UI의 모니터링 횟수가 "-"로 돌아오는지 확인
8. Confirm that after STOP, the running status changes to stopped and the UI monitoring count returns to "-".

주의:
Notes:
- 실제 예약이 발생하지 않도록 운영 계정/날짜 설정을 신중히 다룰 것
- Carefully handle production account/date settings so no real reservation is made.
- 테스트 중 발견한 문제만 수정하고, 예약 비즈니스 로직은 건드리지 말 것
- Fix only issues found during testing, and do not touch the reservation business logic.
```

**완료 기준:**
- 서버 시작 및 Admin API 호출이 실패하지 않는다.
- Admin UI가 새 컬럼만 표시한다.
- 모니터링 횟수가 START 이후 증가하고 STOP 후 숨겨진다.
