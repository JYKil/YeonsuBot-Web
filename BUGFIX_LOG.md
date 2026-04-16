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

## [2026-04-17] Slack 예약 성공 알림 — 체크아웃 날짜 오류
- **증상**: Slack 예약 완료 메시지에서 체크인/아웃이 `20260506~20260506`으로 동일하게 표시 (실제 체크아웃은 20260507)
- **원인**: `_send_slack_success()`에서 `checkout=self._target_dates[-1]`로 전달. `target_dates`는 숙박일만 포함하고 체크아웃일은 제외된 구조(`[checkin, checkout)`)이므로, 1박 예약 시 `[0]`과 `[-1]`이 동일한 날짜가 됨.
- **수정**: `checkout`을 `target_dates[-1] + 1일`로 계산하여 실제 체크아웃 날짜 전달
- **파일**: `scheduler.py` (`_send_slack_success()`)
