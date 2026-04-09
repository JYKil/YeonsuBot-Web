# 서울특별시 연수원 자동 예약 (Yeonsu-Bot)

## 프로젝트 개요

서울시 공무원 연수원(https://yeonsu.eseoul.go.kr/) 예약 가능 날짜를 주기적으로 모니터링하고, 빈방 발견 시 자동 예약하는 데스크톱 앱.

## 아키텍처

- **main.py**: 진입점, 로깅 설정 후 GUI 실행
- **gui.py**: CustomTkinter 기반 GUI. 설정/안내 탭, 상태 표시, 로그 영역. `MonitorScheduler`와 콜백으로 통신
- **checker.py**: `BrowserSession` 클래스. Playwright로 로그인 → 연수원 선택 → 달력 조회 → 자동 예약 (7단계 플로우: 연수원 선택 → 달력 체크인/체크아웃 날짜 클릭 → hidden 필드 동기화 → 선택일로 예약하기 → 기관배정 팝업 닫기 → 객실선택하기 → 예약하기 → 예약안내 팝업 동의). Playwright 네이티브 클릭(trusted event) 사용. 체크아웃은 1박/다박 무관하게 항상 명시적 클릭하며, 다음날 예약 불가 시 사이트 자동 설정 허용. `check_in_day_hidden` → `check_in_day` 필드 동기화 필수. `stop_event`를 받아 주요 단계마다 중지 체크.
- **scheduler.py**: `MonitorScheduler` 클래스. 워커 스레드에서 `BrowserSession`을 소유하고 주기적 체크 + 예약 시도. `stop_event`를 `book()`에 전달하여 즉시 중지 대응.
- **notifier.py**: Slack Incoming Webhook 알림 (빈방 발견, 예약 성공, 테스트)
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

## Skill routing

When the user's request matches an available skill, ALWAYS invoke it using the Skill
tool as your FIRST action. Do NOT answer directly, do NOT use other tools first.
The skill has specialized workflows that produce better results than ad-hoc answers.

Key routing rules:
- Product ideas, "is this worth building", brainstorming → invoke office-hours
- Bugs, errors, "why is this broken", 500 errors → invoke investigate
- Ship, deploy, push, create PR → invoke ship
- QA, test the site, find bugs → invoke qa
- Code review, check my diff → invoke review
- Update docs after shipping → invoke document-release
- Weekly retro → invoke retro
- Design system, brand → invoke design-consultation
- Visual audit, design polish → invoke design-review
- Architecture review → invoke plan-eng-review
- Save progress, checkpoint, resume → invoke checkpoint
- Code quality, health check → invoke health
