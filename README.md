# 서울특별시 연수원 자동 예약 (Yeonsu-Bot)

놀러다니기 좋아하는 내 친구 한수를 위해 만드는 서울시 공무원 연수원 자동 예약 프로그램

## 기능

- 10개 연수원 예약 가능 날짜 자동 모니터링
- 전체 범위 빈방 발견 시 자동 예약
- Slack 알림 (빈방 발견, 예약 성공/실패)
- 설정 자동 저장/복원 (settings.json)
- 세션 만료 시 자동 재로그인
- 메모리 누수 방지를 위한 브라우저 주기적 재시작
- 자동화 탐지 우회 (headless 비활성화, webdriver 플래그 제거, 랜덤 대기)

## 지원 연수원

속초수련원, 서천연수원, 수안보연수원, 제주연수원, 통영마리나연수원, 경주연수원, 엘리시안강촌연수원, 블룸비스타연수원, 여수히든베이연수원, 여수베네치아연수원

## 설치 및 실행

### 요구사항

- Python 3.14+
- Chrome 또는 Edge 브라우저

### 설치

```bash
# 의존성 설치 (uv 사용)
uv sync

# Playwright 브라우저 드라이버 설치
uv run playwright install
```

### 실행

```bash
uv run python main.py
```

### Windows EXE 빌드

GitHub에서 `v*` 태그를 push하면 GitHub Actions가 자동으로 Windows EXE를 빌드합니다.

```bash
git tag v1.0.0
git push origin v1.0.0
```

또는 [Actions 탭](../../actions)에서 수동 실행할 수 있습니다.

## 사용 방법

1. **설정 탭**에서 아이디, 비밀번호, 연수원, 체크인/체크아웃, 확인 간격을 입력
2. **시작** 버튼을 누르면 자동으로 모니터링 + 예약 진행
3. 예약 완료 시 Slack 알림 후 자동 정지
4. 예약 실패 시 Slack 알림 후 모니터링 계속

## UI 디자인 시안

**[디자인 시안 보러가기](https://jykil.github.io/Yeonsu-Bot/)**

4가지 화면 상태를 볼 수 있습니다:
- 대기 중 (시작 전)
- 모니터링 중 (빈방 찾는 중)
- 예약 진행 중 (빈방 발견, 자동 예약 시도)
- 예약 완료

## 프로젝트 구조

```
Yeonsu-Bot/
├── main.py          # 진입점 — GUI 앱 실행
├── gui.py           # CustomTkinter GUI (설정, 상태, 로그)
├── checker.py       # Playwright 기반 예약 가능 확인 + 자동 예약
├── scheduler.py     # Playwright 전용 워커 스레드 + 주기적 모니터링
├── notifier.py      # Slack 웹훅 알림 전송
├── config.py        # 설정 저장/불러오기 (settings.json)
├── facilities.py    # 연수원 목록 및 코드 매핑
├── requirements.txt # 의존성 목록
├── pyproject.toml   # 프로젝트 메타데이터 (uv)
└── docs/            # UI 디자인 시안 (GitHub Pages)
```

## 기술 스택

| 항목 | 선택 |
|------|-----|
| GUI | Python 3 + CustomTkinter |
| 브라우저 자동화 | Playwright (시스템 Chrome/Edge) |
| HTTP | requests |
| 달력 위젯 | tkcalendar |
| 빌드/배포 | PyInstaller (Windows .exe) |
| 알림 | Slack Incoming Webhook |
| CI | GitHub Actions |

## 주의사항

- **2026-06-02**: GitHub Actions Node.js 20 지원 종료 → `actions/checkout@v4`, `actions/setup-python@v5`를 Node.js 24 지원 버전으로 업그레이드 필요
