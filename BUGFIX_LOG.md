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
