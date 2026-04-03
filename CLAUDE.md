# 서울특별시 연수원 자동 예약 (Yeonsu-Bot)

## 프로젝트 개요

서울시 공무원 연수원(https://yeonsu.eseoul.go.kr/) 예약 가능 날짜를 주기적으로 모니터링하고, 빈방 발견 시 자동 예약하는 데스크톱 앱.

## 아키텍처

- **main.py**: 진입점, 로깅 설정 후 GUI 실행
- **gui.py**: CustomTkinter 기반 GUI. 설정/안내 탭, 상태 표시, 로그 영역. `MonitorScheduler`와 콜백으로 통신
- **checker.py**: `BrowserSession` 클래스. Playwright로 로그인 → 연수원 선택 → 달력 조회 → 자동 예약 (8단계 플로우)
- **scheduler.py**: `MonitorScheduler` 클래스. 워커 스레드에서 `BrowserSession`을 소유하고 주기적 체크 + 예약 시도
- **notifier.py**: Slack Incoming Webhook 알림 (빈방 발견, 예약 성공/실패, 테스트)
- **config.py**: settings.json 저장/불러오기, 비밀번호 Base64 인코딩
- **facilities.py**: 10개 연수원 이름↔코드 매핑

## 실행 방법

```bash
uv sync && uv run python main.py
```

## 빌드

GitHub Actions (`build-exe.yml`)로 Windows EXE 자동 빌드. `v*` 태그 push 또는 수동 실행.

## gstack

- 웹 브라우징은 항상 `/browse` 스킬을 사용할 것
- `mcp__claude-in-chrome__*` 도구는 절대 사용하지 말 것
- 사용 가능한 스킬: /office-hours, /plan-ceo-review, /plan-eng-review, /plan-design-review, /design-consultation, /design-shotgun, /design-html, /review, /ship, /land-and-deploy, /canary, /benchmark, /browse, /connect-chrome, /qa, /qa-only, /design-review, /setup-browser-cookies, /setup-deploy, /retro, /investigate, /document-release, /codex, /cso, /autoplan, /careful, /freeze, /guard, /unfreeze, /gstack-upgrade, /learn
- gstack 스킬이 작동하지 않으면 `cd .claude/skills/gstack && ./setup` 을 실행하여 바이너리를 빌드하고 스킬을 등록할 것
