# 서울특별시 연수원 자동 예약 (Yeonsu-Bot Web)

놀러다니기 좋아하는 내 친구 한수를 위해 만드는 서울시 공무원 연수원 자동 예약 프로그램

브라우저에서 접속해 사용하는 웹 버전. 본인 1명 전용, 한 번에 한 세션만 돌리는 **단일 슬롯** 구조. Oracle Cloud Free Tier VM에 Docker로 배포.

## 기능

- 10개 연수원 예약 가능 날짜 자동 모니터링
- 전체 범위 빈방 발견 시 자동 예약 → 성공 시 자동 중지
- 실시간 로그 스트리밍 (WebSocket)
- 재접속/새 탭 열어도 최근 200줄 로그 복원
- 설정 자동 저장/복원 (`settings.json`)
- Slack 알림 (예약 성공/실패)
- 세션 만료 시 자동 재로그인
- 메모리 누수 방지를 위한 브라우저 주기적 재시작
- 장시간 대기 UX: 마지막/다음 확인 시각 + 대상 표시

## 지원 연수원

속초수련원, 서천연수원, 수안보연수원, 제주연수원, 통영마리나연수원, 경주연수원, 엘리시안강촌연수원, 블룸비스타연수원, 여수히든베이연수원, 여수베네치아연수원

## 사용 방법

1. 브라우저에서 `http://<서버IP>:8000` 접속
2. 아이디, 비밀번호, 연수원, 체크인/체크아웃, 확인 간격 입력
3. **시작** 버튼 클릭 → 자동 모니터링 + 예약 진행
4. 상태 뱃지로 진행 상황 확인 (`마지막 확인: 09:23 · 다음 확인: 09:25`)
5. 예약 완료 시 Slack 알림 후 자동 중지 + "예약완료" 뱃지

## 디자인

- 디자인 시스템: `DESIGN.md` (Apple 시스템, SF Pro, `#0071e3`, `#f5f5f7`)
- 정적 목업: `mockups/index.html` (브라우저로 열어 확인)
- 단일 패널 UI — 설정 패널 좌(40%) / 로그 뷰어 우(60%), 모바일 시 세로 스택

## 배포 (Docker + Oracle Cloud)

### 요구사항

- Docker, Docker Compose
- Oracle Cloud Free Tier VM (ARM `VM.Standard.A1.Flex` — 1 OCPU / 6GB 충분)

### Oracle Cloud VM 방화벽 설정

Oracle Cloud Security List와 Ubuntu iptables 양쪽 모두 열어야 합니다.

```bash
# Oracle Cloud Console → Security List → Ingress Rule 추가
# TCP 22 (SSH), TCP 8000 (앱)

# VM 내부 iptables
sudo iptables -I INPUT 6 -m state --state NEW -p tcp --dport 8000 -j ACCEPT
sudo netfilter-persistent save
```

### 배포

```bash
# Docker 설치 (VM 최초 1회)
sudo apt update && sudo apt install -y docker.io docker-compose-plugin
sudo usermod -aG docker ubuntu && newgrp docker

# 앱 클론 및 실행
git clone https://github.com/JYKil/YeonsuBot-Web /opt/yeonsubot
cd /opt/yeonsubot
mkdir -p data
docker compose up -d --build
```

접속: `http://<Oracle-VM-공용-IP>:8000`

### 로컬 테스트

```bash
docker compose up --build
# http://localhost:8000 접속
```

### 로컬 개발 (Docker 없이)

```bash
uv sync                    # 최초 1회, pyproject.toml 기준 .venv 생성
uv run python main.py      # FastAPI + uvicorn 기동
# http://localhost:8000 접속
```

macOS/Windows에 Google Chrome이 설치돼 있으면 시스템 Chrome을 자동 감지해서 사용하고, 없으면 Playwright 내장 Chromium으로 폴백합니다. 첫 실행 시 내장 Chromium이 필요하면 `uv run playwright install chromium` 한 번 돌리면 됩니다.

## 프로젝트 구조

```
YeonsuBot-Web/
├── main.py           # FastAPI 진입점 (uvicorn)
├── web_server.py     # FastAPI 앱 (AppState, /ws, lifespan)
├── checker.py        # Playwright 기반 예약 확인 + 자동 예약 (headless 폴백 포함)
├── scheduler.py      # 워커 스레드 + 주기적 모니터링
├── notifier.py       # Slack 웹훅 알림
├── config.py         # settings.json 저장/불러오기 (SETTINGS_DIR 환경변수)
├── facilities.py     # 10개 연수원 이름↔코드 매핑
├── templates/
│   └── index.html    # 단일 패널 UI (Vanilla JS)
├── mockups/
│   └── index.html    # 정적 디자인 목업 (참고용)
├── requirements.txt  # 의존성 목록
├── Dockerfile
├── docker-compose.yml
├── plan.md           # 웹 전환 계획 + 디자인 토큰
├── to-do.md          # 작업 체크리스트
└── data/             # settings.json (Docker 볼륨 마운트)
```

## 기술 스택

| 항목 | 선택 |
|------|-----|
| 웹 프레임워크 | FastAPI + uvicorn |
| 실시간 통신 | WebSocket (단일 `/ws`) |
| 프론트엔드 | Vanilla JS (단일 HTML) |
| 디자인 시스템 | Apple 시스템 (SF Pro, `#0071e3`) |
| 브라우저 자동화 | Playwright (headless Chromium, Linux에서 내장 Chromium 사용) |
| HTTP | requests |
| 알림 | Slack Incoming Webhook |
| 컨테이너 | Docker (`mcr.microsoft.com/playwright/python`) |
| 배포 | Oracle Cloud Free Tier (ARM VM) |

## 주의사항

- 본인 1명 전용 설계입니다. 한 번에 한 세션만 돌아갑니다 (실행 중 `/api/start` 재호출 시 409 응답).
- 단일 Chromium 인스턴스 기준 약 300~400MB RAM 사용. ARM Free Tier 1 OCPU / 6GB 로 충분합니다.
- `data/` 디렉토리가 Docker 볼륨으로 마운트되어 설정이 컨테이너 재시작 후에도 유지됩니다.
- 웹 인증 기능이 없습니다 (URL 알면 접근 가능). 공용 환경에 띄울 계획이면 HTTPS/인증 레이어를 앞에 두세요.
