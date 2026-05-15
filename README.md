# 서울특별시 연수원 자동 예약 (Yeonsu-Bot Web)

놀러다니기 좋아하는 내 친구 한수를 위해 만드는 서울시 공무원 연수원 자동 예약 프로그램

브라우저에서 접속해 사용하는 웹 버전. 최대 3명이 각자 계정으로 동시 로그인해 독립적으로 봇을 운영할 수 있는 **멀티유저** 구조. Beelink EQR6 미니 PC(Ubuntu)에 Docker로 배포, GitLab + Jenkins CI/CD.

## 기능

- 연수원 사이트 자격(아이디/비밀번호)으로 로그인, 최대 3명 동시 사용
- 10개 연수원 예약 가능 날짜 자동 모니터링
- 전체 범위 빈방 발견 시 자동 예약 → 성공 시 자동 중지
- 실시간 로그 스트리밍 (WebSocket, 사용자별 격리)
- 재접속/새 탭 열어도 최근 200줄 로그 복원
- 사용자별 설정 자동 저장/복원 (`data/users/<username>/settings.json`)
- Admin 현황판 (`/admin`)에서 계정별 실행 상태와 모니터링 횟수를 읽기 전용으로 확인
- 세션 만료 시 자동 재로그인
- 메모리 누수 방지를 위한 브라우저 주기적 재시작
- 장시간 대기 UX: 마지막/다음 확인 시각 + 대상 표시
- 같은 브라우저 프로필에서 창 여러 개로 서로 다른 계정 동시 운용 가능 (sessionStorage 기반 창별 세션 격리)

## 지원 연수원

속초수련원, 서천연수원, 수안보연수원, 제주연수원, 통영마리나연수원, 경주연수원, 엘리시안강촌연수원, 블룸비스타연수원, 여수히든베이연수원, 여수베네치아연수원

## 배포 주소

- **앱**: http://kilga-server.duckdns.org:3000
- **Admin**: http://kilga-server.duckdns.org:3000/admin

## 사용 방법

1. 브라우저에서 http://kilga-server.duckdns.org:3000 접속
2. 연수원 사이트 아이디/비밀번호로 로그인 (최초 로그인 시 연수원 사이트 인증 포함, 5~10초 소요)
3. 연수원, 체크인/체크아웃, 확인 간격 선택
4. **START** 버튼 클릭 → 자동 모니터링 + 예약 진행
5. 상태 뱃지로 진행 상황 확인
6. 예약 완료 시 자동 중지 + "예약완료" 뱃지
7. 로그아웃 버튼으로 세션 종료

## Admin 현황판

- 접속 경로: `http://kilga-server.duckdns.org:3000/admin`
- 운영 URL: http://kilga-server.duckdns.org:3000/admin
- 인증: `.env`의 `ADMIN_PASSWORD` 값을 입력
- 표시 정보: 계정명, 최근 로그인, 실행 여부, 현재 상태, 모니터링 횟수
- 표시하지 않는 정보: 비밀번호, 세션 토큰, 예약 대상 연수원/날짜, 로그 내용

## 디자인

- 디자인 시스템: `DESIGN.md` (Apple 시스템, SF Pro, `#0071e3`, `#f5f5f7`)
- 정적 목업: `mockups/index.html` (브라우저로 열어 확인)
- 단일 패널 UI — 설정 패널 좌(40%) / 로그 뷰어 우(60%), 모바일 시 세로 스택
- 모바일에서 체크인/체크아웃 날짜 필드 한 줄 나란히 배치

## 배포 (Docker + Beelink + CI/CD)

### 요구사항

- Beelink EQR6 (Ubuntu, x86_64)
- Docker, Docker Compose
- GitLab (http://kilga-server.duckdns.org:8929)
- Jenkins (http://kilga-server.duckdns.org:8080)

### CI/CD 흐름

GitLab push → Jenkins 웹훅 자동 트리거 → 빌드 + 배포 + 헬스체크

```bash
# 코드 변경 후 push만 하면 자동 배포
git push gitlab master
```

Jenkins 파이프라인 (`Jenkinsfile`):
1. 준비 — `mkdir -p data`
2. 빌드 — `docker compose build --pull`
3. 배포 — `docker compose up -d --force-recreate`
4. 헬스체크 — `curl http://localhost:3000/api/status`

배포 디렉토리: `/opt/yeonsubot` (settings.json이 이 경로 아래 영속)

### 환경변수 설정

운영 서버의 배포 디렉토리에서 `.env.example`을 복사해 `.env`를 만들고 admin 비밀번호를 설정합니다.

```bash
cd /opt/yeonsubot
cp .env.example .env
nano .env
```

```env
ADMIN_PASSWORD=원하는관리자비밀번호
```

`docker-compose.yml`은 `.env`를 optional env file로 읽습니다. `.env`가 없으면 컨테이너는 뜨지만 admin API는 비활성화됩니다.

### Jenkins 초기 설정 (최초 1회)

```bash
# Jenkins 사용자에게 Docker 권한 부여
sudo usermod -aG docker jenkins
sudo systemctl restart jenkins

# 배포 디렉토리 생성 및 권한 설정
sudo mkdir -p /opt/yeonsubot/data
sudo chown -R jenkins:jenkins /opt/yeonsubot
```

### 로컬 테스트

```bash
docker compose up --build
# http://localhost:3000 접속
# admin: http://localhost:3000/admin
```

### 로컬 개발 (Docker 없이)

```bash
uv sync                    # 최초 1회, pyproject.toml 기준 .venv 생성
ADMIN_PASSWORD=원하는관리자비밀번호 uv run python main.py
# http://localhost:3000 접속
```

macOS/Windows에 Google Chrome이 설치돼 있으면 시스템 Chrome을 자동 감지해서 사용하고, 없으면 Playwright 내장 Chromium으로 폴백합니다. Docker(Linux) 환경에서는 Playwright 내장 Chromium을 사용합니다.

## 프로젝트 구조

```
YeonsuBot-Web/
├── main.py           # FastAPI 진입점 (uvicorn)
├── web_server.py     # FastAPI 앱 (SessionContext, SchedulerRegistry, /ws, admin API, lifespan)
├── auth.py           # 세션 관리 (create/resolve/destroy, current_user/current_admin dependency)
├── log_context.py    # USER_CTX ContextVar (워커 스레드 → 로그 핸들러 사용자 식별)
├── checker.py        # Playwright 기반 예약 확인 + 자동 예약 (Chromium 폴백 포함)
├── scheduler.py      # 워커 스레드 + 주기적 모니터링
├── notifier.py       # 알림 모듈 (현재 미사용, 텔레그램 전환 예정)
├── config.py         # 사용자별 settings.json 저장/불러오기 (SETTINGS_DIR 환경변수)
├── migrate.py        # 일회성 마이그레이션 (settings.json → users/<username>/)
├── facilities.py     # 10개 연수원 이름↔코드 매핑
├── templates/
│   ├── index.html    # 멀티유저 UI (로그인 카드 + 메인 패널, Vanilla JS)
│   └── admin.html    # Admin 현황판 UI (읽기 전용, Vanilla JS)
├── mockups/
│   └── index.html    # 정적 디자인 목업 (참고용)
├── requirements.txt  # 의존성 목록
├── Dockerfile
├── docker-compose.yml
├── DESIGN.md         # Apple 시스템 디자인 토큰
├── BUGFIX_LOG.md     # 운영 중 버그 수정 이력
└── data/
    └── users/
        └── <username>/
            └── settings.json   # 사용자별 설정 (Docker 볼륨 마운트)
```

## 기술 스택

| 항목 | 선택 |
|------|-----|
| 웹 프레임워크 | FastAPI + uvicorn |
| 실시간 통신 | WebSocket (단일 `/ws`) |
| 프론트엔드 | Vanilla JS (단일 HTML) |
| 디자인 시스템 | Apple 시스템 (SF Pro, `#0071e3`) |
| 브라우저 자동화 | Playwright (로컬: 시스템 Chrome 감지, Docker/ARM64: Chromium) |
| HTTP | requests |
| 알림 | 미사용 (텔레그램 전환 예정) |
| 컨테이너 | Docker (`mcr.microsoft.com/playwright/python`) |
| 배포 | Beelink EQR6 (Ubuntu, x86_64) + Docker + GitLab/Jenkins CI/CD |

## 주의사항

- 동시 로그인 및 봇 실행은 최대 3명으로 제한됩니다. 초과 시 503 안내가 표시됩니다.
- 사용자 1명당 Chromium 인스턴스 약 300~400MB RAM 사용. 3명 동시 실행 시 최대 ~1.2GB.
- 세션은 서버 메모리에만 저장됩니다. 컨테이너 재시작 시 모두 로그아웃되며, 재로그인하면 설정은 복원됩니다.
- `data/users/` 디렉토리가 Docker 볼륨으로 마운트되어 사용자별 설정이 재시작 후에도 유지됩니다.
- 기존 `data/settings.json`이 있다면 `python migrate.py`를 한 번 실행해 사용자별 경로로 이전하세요.
