# 서울특별시 연수원 자동 예약 (Yeonsu-Bot Web)

놀러다니기 좋아하는 내 친구 한수를 위해 만드는 서울시 공무원 연수원 자동 예약 프로그램

브라우저에서 접속해 사용하는 웹 버전. Oracle Cloud Free Tier VM에 Docker로 배포.

## 기능

- 10개 연수원 예약 가능 날짜 자동 모니터링
- 전체 범위 빈방 발견 시 자동 예약
- **최대 3개 계정을 독립 슬롯으로 동시 실행** (각각 다른 연수원/날짜 설정 가능)
- Slack 알림 (예약 성공 시 `[Slot N]` 슬롯 번호 포함)
- 설정 자동 저장/복원 (슬롯별 `settings_0.json`, `settings_1.json`, `settings_2.json`)
- 세션 만료 시 자동 재로그인
- 메모리 누수 방지를 위한 브라우저 주기적 재시작
- 실시간 로그 스트리밍 (WebSocket)
- 재접속/새 탭 열어도 최근 200줄 로그 복원

## 지원 연수원

속초수련원, 서천연수원, 수안보연수원, 제주연수원, 통영마리나연수원, 경주연수원, 엘리시안강촌연수원, 블룸비스타연수원, 여수히든베이연수원, 여수베네치아연수원

## 사용 방법

1. 브라우저에서 `http://<서버IP>:8000` 접속
2. **슬롯 탭** ([슬롯 1] [슬롯 2] [슬롯 3]) 에서 사용할 슬롯 선택
3. 아이디, 비밀번호, 연수원, 체크인/체크아웃, 확인 간격 입력
4. **시작** 버튼 클릭 → 자동 모니터링 + 예약 진행
5. 예약 완료 시 Slack 알림 후 해당 슬롯 자동 정지
6. 탭 레이블의 `●` 표시로 어느 슬롯이 실행 중인지 한눈에 파악 가능

## 배포 (Docker + Oracle Cloud)

### 요구사항

- Docker, Docker Compose
- Oracle Cloud Free Tier VM (ARM `VM.Standard.A1.Flex` 권장 — 2 OCPU / 12GB)

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
git clone https://github.com/JYKil/yeonsu-bot /opt/yeonsubot
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

## 프로젝트 구조

```
YeonsuBot-Web/
├── main.py           # FastAPI 진입점
├── web_server.py     # FastAPI 앱 (SlotState×3, /ws/{slot_id}, lifespan)
├── checker.py        # Playwright 기반 예약 확인 + 자동 예약
├── scheduler.py      # 워커 스레드 + 주기적 모니터링
├── notifier.py       # Slack 웹훅 알림 (slot_label 포함)
├── config.py         # 슬롯별 설정 저장/불러오기 (settings_{n}.json)
├── facilities.py     # 연수원 목록 및 코드 매핑
├── templates/
│   └── index.html    # 탭 UI (슬롯 3개, Vanilla JS)
├── requirements.txt  # 의존성 목록
├── Dockerfile
├── docker-compose.yml
└── data/             # settings_0.json, settings_1.json, settings_2.json (볼륨)
```

## 기술 스택

| 항목 | 선택 |
|------|-----|
| 웹 프레임워크 | FastAPI + uvicorn |
| 실시간 통신 | WebSocket (슬롯별 `/ws/{slot_id}`) |
| 프론트엔드 | Vanilla JS (단일 HTML) |
| 브라우저 자동화 | Playwright (headless Chromium) |
| HTTP | requests |
| 알림 | Slack Incoming Webhook |
| 컨테이너 | Docker (`mcr.microsoft.com/playwright/python`) |
| 배포 | Oracle Cloud Free Tier (ARM VM) |

## 주의사항

- 슬롯 3개 동시 실행 시 Chromium × 3 = 약 900MB RAM 사용. AMD Micro (1GB) 인스턴스에서는 부족할 수 있으므로 ARM Free Tier 사용 권장.
- `data/` 디렉토리가 Docker 볼륨으로 마운트되어 설정이 컨테이너 재시작 후에도 유지됩니다.
