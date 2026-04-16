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

## [2026-04-16] 객실선택하기(termType) 미발견 — search() 중복 호출
- **증상**: 객실 목록 페이지에서 `input[name="termType"]` 10초 타임아웃. 수동 브라우징에서는 동일 URL에서 객실 정상 표시.
- **원인**: `page.goto(list_url)` 시 사이트 JS가 URL 파라미터를 감지하여 **자동으로 search() 실행** (alert #1 + AJAX 로드). 이후 코드가 `search()`를 명시적으로 **다시 호출**하여 진행 중이던 AJAX를 중단/초기화 (alert #2). 두 번째 search()의 AJAX 응답이 정상 완료되지 않아 `#room_contents`가 빈 상태로 남음.
- **수정**: goto() 후 `input[name="termType"]` 존재 여부를 먼저 확인하고, 이미 로드됐으면 search() 건너뜀. 에러 진단도 `body_text` → `#room_contents` innerHTML 덤프로 개선.
- **파일**: `checker.py` (book() 3단계, 5단계)
