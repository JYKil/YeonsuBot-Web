# 버그 수정 기록

## [2026-04-16] 달력 가용 날짜 판정 오류
- **증상**: 예약 가능 날짜가 있는데 "가능 날짜 없음"으로 판정 (`불가 [...], 가능 []`)
- **원인**: `_JS_READ_CALENDAR`가 `<button>` 요소만 확인하여 `td.onclick` 기반 가용 날짜를 놓침. 연수원 사이트는 가용 날짜에 `td` 자체에 `onclick` 핸들러를 붙이는 구조인데, 판정 JS는 내부 `<button>` 요소만 검사.
- **수정**: `typeof td.onclick === 'function'` 조건 추가, 대기 셀렉터에 `td.targetDate[onclick]` 추가
- **파일**: `checker.py` (`_JS_READ_CALENDAR`, 버튼 대기 셀렉터)
