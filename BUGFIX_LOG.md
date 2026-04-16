# 버그 수정 기록

## [2026-04-16] 달력 가용 날짜 판정 오류
- **증상**: 예약 가능 날짜가 있는데 "가능 날짜 없음"으로 판정 (`불가 [...], 가능 []`)
- **원인**: `_JS_READ_CALENDAR`가 `<button>` 요소만 확인하여 `td.onclick` 기반 가용 날짜를 놓침. 연수원 사이트는 가용 날짜에 `td` 자체에 `onclick` 핸들러를 붙이는 구조인데, 판정 JS는 내부 `<button>` 요소만 검사.
- **수정**: `typeof td.onclick === 'function'` 조건 추가, 대기 셀렉터에 `td.targetDate[onclick]` 추가
- **파일**: `checker.py` (`_JS_READ_CALENDAR`, 버튼 대기 셀렉터)

## [2026-04-16] 객실 목록 미로드 — search() 미호출
- **증상**: 날짜 포함 URL로 이동 후 "객실선택하기 버튼을 찾을 수 없음" (10초 타임아웃)
- **원인**: URL 파라미터(`check_in_day`, `check_out_day`)만으로는 객실 목록 AJAX가 자동 실행되지 않음. `#room_contents`는 DOM에 존재하지만 빈 상태. `search()` 함수를 명시적으로 호출해야 객실 데이터가 로드됨.
- **수정**: URL 이동 후 폼 필드 설정 + `search()` 명시적 호출 추가
- **파일**: `checker.py` (book() 3단계)

## [2026-04-16] 객실선택하기(termType) 미발견 — search() 중복 호출 (1차 수정)
- **증상**: 객실 목록 페이지에서 `input[name="termType"]` 10초 타임아웃. 수동 브라우징에서는 동일 URL에서 객실 정상 표시.
- **원인**: `page.goto(list_url)` 시 사이트 JS가 URL 파라미터를 감지하여 **자동으로 search() 실행** (alert #1 + AJAX 로드). 이후 코드가 `search()`를 명시적으로 **다시 호출**하여 진행 중이던 AJAX를 중단/초기화 (alert #2). 두 번째 search()의 AJAX 응답이 정상 완료되지 않아 `#room_contents`가 빈 상태로 남음.
- **수정**: goto() 후 `input[name="termType"]` 존재 여부를 먼저 확인하고, 이미 로드됐으면 search() 건너뜀. 에러 진단도 `body_text` → `#room_contents` innerHTML 덤프로 개선.
- **파일**: `checker.py` (book() 3단계, 5단계)

## [2026-04-16] 서버 세션 미갱신 — change 이벤트 미발생으로 잘못된 연수원 기준 동작
- **증상**: 여수히든베이연수원을 선택했으나 "블룸비스타 연수원 개인 예약은 매월 16일 16:00부터 예약 가능합니다" alert 발생. 수동 로그인 시에는 alert 없음. #room_contents EMPTY로 예약 실패.
- **원인**: `sel.value = code`는 클라이언트 DOM만 변경하고 `onchange` 핸들러를 실행하지 않음. 사이트의 `showCalendar()`, `search()` 등은 서버 세션의 현재 시설 기준으로 동작. URL 파라미터(`?ser_yeonsu_gbn=00003010`)로 페이지는 렌더링되지만 서버 세션은 갱신되지 않아 이전 세션의 시설(블룸비스타 추정)로 달력/검색이 실행됨. 수동으로 드롭다운 선택 시 `onchange` 발생 → 서버 세션 갱신 → 정상 동작.
- **수정**: `sel.dispatchEvent(new Event('change', {bubbles: true}))` 추가 → onchange 핸들러 실행 → 서버 세션 갱신. `change` 이벤트 후 networkidle 대기(최대 5초). 실제 select 값을 로그로 확인.
- **파일**: `checker.py` (check() 연수원 선택, book() 1단계 연수원 선택)

## [2026-04-16] #room_contents EMPTY — networkidle 타임아웃 시 폼 필드 미설정
- **증상**: networkidle 타임아웃 후 search() 호출 시 URL이 base URL(`/onlineRsv/list`, 파라미터 없음)로 변경되고 `#room_contents` EMPTY
- **원인**: networkidle 타임아웃(10초) 시 페이지가 아직 로딩 중 → `#check_in_day` 등 폼 요소가 DOM에 없음 → `getElementById` null 반환 → `if (ciEl) ciEl.value = ci` 조건에 막혀 날짜 값 설정 안 됨 → search()가 빈 폼으로 실행 → 빈 파라미터로 base URL 이동 → 객실 미로드
- **수정**: networkidle 후 `page.wait_for_selector('#check_in_day', state='attached', timeout=10000)`로 폼 요소 존재 보장. 폼 필드 설정 evaluate에서 설정 성공 여부 반환하여 로그로 확인. search() 호출 전 현재 URL 로깅.
- **파일**: `checker.py` (book() 3단계)

## [2026-04-17] 달력 가용 날짜 판정 오류 (2차) — onclick 기반 판정이 불가 날짜를 가능으로 오판
- **증상**: 20260507이 예약 불가(달력에 파란 원 없음, button disabled)인데 로그에서 "가능"으로 판정 (`가능 ['20260506', '20260507']`)
- **원인**: 사이트는 **모든 td**에 `onclick="rsvList(...)"` 속성을 붙임. 4/16 수정에서 추가한 `typeof td.onclick === 'function'` 체크가 항상 true 반환 → `hasOnclick || btnOk`에서 disabled button을 가진 불가 날짜도 가능으로 판정. HTML 구조: 가능=`<button>` enabled, 불가=`<button class="day-prev" disabled="disabled">`
- **수정**: `hasOnclick` 변수 및 OR 조건 제거, `btnOk`(button enabled + day-prev 아님)만으로 판정
- **파일**: `checker.py` (`_JS_READ_CALENDAR`)

## [2026-04-17] Slack 예약 성공 알림 — 날짜 표시 오류 (3건)
- **증상 1**: 체크인/아웃이 `20260506~20260506`으로 동일하게 표시 (실제 체크아웃은 20260507)
- **원인 1**: `_send_slack_success()`에서 `checkout=self._target_dates[-1]`로 전달. `target_dates`는 숙박일만 포함(`[checkin, checkout)`)하므로 1박 시 `[0]`과 `[-1]`이 동일.
- **수정 1**: `checkout`을 `target_dates[-1] + 1일`로 계산 (`scheduler.py`)
- **증상 2**: 체크아웃 수정 후에도 체크인/아웃이 `20260507~20260508` (YYYYMMDD 원본 그대로 출력, MM-DD 포맷 안 됨)
- **원인 2**: `notifier.py`의 `checkin[5:] if len(checkin) >= 10`이 YYYY-MM-DD(10자)만 처리, scheduler는 YYYYMMDD(8자)로 전달
- **수정 2**: YYYYMMDD(8자) 형식도 `MM-DD`로 변환하도록 포맷 로직 추가 (`notifier.py`)
- **증상 3**: 예약일이 체크인 날짜(`05-07`)로 표시, 실제 예약 수행일(오늘)이 아님
- **원인 3**: `booked_date=self._target_dates[0]`으로 체크인 날짜 전달
- **수정 3**: `datetime.now().strftime("%m-%d %H:%M")`으로 실제 예약 수행 시점 표시 (`notifier.py`)
- **파일**: `scheduler.py` (`_send_slack_success()`), `notifier.py` (`send_booking_success()`)

## [2026-04-17] 달력 가용 날짜 판정 오류 (3차) — 다음 달 로딩 지연으로 가능 날짜 오판
- **증상**: 여수베네치아연수원 20260506이 예약 가능(button enabled)인데 "불가"로 판정. 재시도 1~2회는 td 자체 미발견, 3회째 td 발견했으나 button disabled 상태
- **원인**: 달력이 4월/5월 두 달을 표시하며 4월이 먼저 로드됨. 기존 대기(`td.targetDate[data-date]`, `button:not([disabled])`)가 4월 요소로 충족되어 5월 달력이 완전 로드되기 전에 판정 시작. 재시도 3회(~4초)로는 5월 button 활성화 전에 포기.
- **수정**: (1) 대상 날짜 td가 DOM에 나타날 때까지 명시적 대기 추가 (2) 재시도 횟수 3→5회로 증가하여 button 로딩 시간 확보
- **파일**: `checker.py` (check() 달력 대기 로직, 재시도 루프)

## [2026-04-17] 점검 결과 후 다음 주기 로그 누락
- **증상**: 달력 결과 로그(`달력 결과: 불가 [...], 가능 []`) 이후 다음 점검까지 로그가 없어 대기 상태인지 알 수 없음
- **수정**: 가능 날짜 없거나 일부만 가능할 때 `다음 점검까지 N초 대기` 로그 추가
- **파일**: `scheduler.py` (`_do_check_and_book()`)

## [2026-04-17] Slack 알림 시간대 오류 + 중복 항목
- **증상**: 예약시간이 "04-16 21:24"로 표시 (실제 KST 04-17 06:24). 서버가 Oracle Cloud VM(UTC)에서 실행되어 `datetime.now()`가 UTC 반환. "확인시간"과 "예약일"이 중복.
- **수정**: (1) 모든 `datetime.now()` → `datetime.now(KST)` 적용 (2) `send_booking_success()`에서 "확인시간" 삭제 (3) "예약일" → "예약시간"으로 라벨 변경
- **파일**: `notifier.py` (전체 함수)
