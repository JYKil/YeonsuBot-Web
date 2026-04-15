# YeonsuBot 웹 전환 — 작업 목록

## 진행 상황 (2026-04-14)

| Phase | 상태 |
|---|---|
| 선행 — 디자인 리뷰 | ✅ 완료 (6.5 → 9.2/10) |
| Phase 1 — 핵심 로직 | ✅ 완료 |
| Phase 2 — FastAPI 백엔드 | ✅ 완료 |
| Phase 3 — 프론트엔드 | ✅ 완료 |
| Phase 4 — 패키지 & Docker | ✅ 완료 |
| Phase 5 — Oracle Cloud 배포 | ⬜ 대기 |
| Phase 6 — 로컬 검증 | ✅ 완료 (REST + WS smoke + UI 시각 확인) |

---

## 선행 작업

- [x] **`/plan-design-review` 실행** — DESIGN.md Apple 시스템 기준. 디자인 토큰(Color/Typography/Spacing&Radius) 3개 표로 분리, 사용자 저널 + 상태 보조 라인 추가, flat 디자인 확정. 목업 `mockups/index.html` 생성.

---

## 확정된 설계 결정 (2026-04-14)

| 항목 | 결정 |
|------|------|
| 사용 주체 | 본인 1명 전용, 한 번에 한 세션 |
| 봇 슬롯 수 | **1개 고정** |
| 웹앱 인증 | 없음 — 로컬 전용, URL 알면 접근 |
| 실시간 로그 | WebSocket (FastAPI) |
| 예약 성공 후 | 자동 중지 + "예약완료" badge |
| UI 레이아웃 | 단일 패널 — 설정 좌(40%) / 로그 우(60%), flat (shadow 없음) |
| 동시 실행 방지 | `/api/start` 재호출 시 409 응답 |
| 디자인 시스템 | DESIGN.md Apple 시스템 (SF Pro, #0071e3, #f5f5f7) |
| 시작/중지 버튼 | 같은 자리 토글 |

---

## Phase 1: 핵심 로직 수정 ✅

- [x] **`config.py`** — Docker 볼륨 지원
  - `base_dir`를 `os.environ.get("SETTINGS_DIR", ...)` 로 변경
  - `SETTINGS_FILE = os.path.join(base_dir, "settings.json")`
  - `load()` / `save()` 시그니처 변경 없음
  - `os.makedirs(base_dir, exist_ok=True)` 로 SETTINGS_DIR 자동 생성

- [x] **`checker.py`** — Linux headless 환경 대응
  - `_detect_browser_channel()`: 브라우저 못 찾으면 예외 대신 `None` 반환
  - `BrowserSession.start()`: `channel=None` 시 내장 Chromium 사용
  - **시스템 Chrome 있을 때는 `--no-sandbox` 적용 안 함** (로컬 macOS/Windows 샌드박스 유지)
  - 내장 Chromium 사용 시에만 `--no-sandbox`, `--disable-dev-shm-usage` 적용

- [x] **`notifier.py`** — 변경 없음
- [x] **`scheduler.py`, `facilities.py`** — 변경 없음

---

## Phase 2: 백엔드 구현 ✅

- [x] **`web_server.py`** 신규 생성 — FastAPI 앱
  - `AppState` 클래스: `scheduler`, `ws_clients: set[WebSocket]`, `log_buffer: deque(maxlen=200)`, `current_status`, `last_check_at`, `last_result`, `loop`
  - `WebSocketLogHandler` (logging → `ws_clients` 브로드캐스트, `loop.call_soon_threadsafe()` 기반)
  - lifespan 컨텍스트 (앱 종료 시 `scheduler.stop()` + worker join(timeout=15))
  - REST 엔드포인트:
    - `GET /` → index.html
    - `GET /api/status` → `{running, status, last_check_at, next_check_at, target, last_result}`
    - `GET /api/settings` → 설정 로드 (비밀번호 마스킹 `********`) + facilities 목록
    - `POST /api/start` → 설정 저장 + `scheduler.start()` (이미 실행 중이면 409)
    - `POST /api/stop` → `scheduler.stop()`
    - `POST /api/slack/test` → Slack 웹훅 테스트
  - WebSocket 엔드포인트: `WS /ws` (연결 시 `log_buffer` + 상태 스냅샷 즉시 전송)
  - scheduler 콜백 연결 (on_status_change, on_booking_result, on_error, on_check_result)
  - 비밀번호 마스킹 재사용 로직 (빈 값/마스크 시 저장된 encoded 값 사용)

- [x] **`main.py`** 교체 — FastAPI 진입점
  - 기존 CustomTkinter 코드 제거
  - `uvicorn.run("web_server:app", host, port)` 로 변경
  - `HOST`/`PORT` 환경변수 지원

---

## Phase 3: 프론트엔드 ✅

- [x] **`templates/index.html`** 신규 생성 — 단일 페이지 UI
  - **레이아웃**: 다크 nav 바 + 설정 패널(좌 40%) / 로그 뷰어(우 60%) 2열, flat 디자인
  - **정보 계층**: 상태+액션 → 폼 → 로그 (액션 버튼을 폼 위로 배치)
  - **디자인 토큰**: Color/Typography/Spacing&Radius CSS 변수로 선언, DESIGN.md 행 매핑
  - **상태 뱃지 + 보조 라인**: `마지막 확인: 09:23 · 다음: 09:25 · 대상: 신구로 5/1~5/2`
  - **시작/중지 토글**: 실행 상태에 따라 START 또는 STOP 하나만 노출
  - **설정 폼**: 아이디, 비밀번호 + 표시 토글(aria-pressed), 연수원 드롭다운, 체크인/아웃, 점검주기
    - 체크인 변경 시 체크아웃 자동 +1일
    - `autocomplete="username"` / `"current-password"`
  - **인터랙션 상태**: 빈 상태, 시작 LOADING, 409 토스트, WS 끊김 배너, Slack 테스트 토스트
  - **로그 뷰어**: SF Mono 13px, 컬러 코딩(성공/경고/오류), 자동 스크롤
    - 사용자가 위로 스크롤 시 autoscroll pause + `↓ 새 로그 N건` 버튼
  - **WS**: 연결 시 버퍼 재수신, 끊김 시 3초 후 자동 재연결
  - **예약 성공 시**: "예약완료" 뱃지 + 자동 중지 반영 (statusLabel/statusBadge 형제 hidden 토글로 idempotent 렌더)
  - **접근성**: focus ring 2px `#0071e3`, aria-live, 44px 터치 타겟, `prefers-reduced-motion`
  - **반응형**: 1070px↓ 패널 폭 축소, 640px↓ 세로 스택 (로그 min-height 240px)
  - Slack 테스트 버튼 (설정 패널 하단)

---

## Phase 4: 패키지 및 Docker ✅

- [x] **`requirements.txt`** 업데이트
  - 추가: `fastapi>=0.109.0`, `uvicorn[standard]>=0.27.0`
  - 제거: `customtkinter`, `tkcalendar`, `pyinstaller`

- [x] **`Dockerfile`** 신규 생성
  - 베이스: `mcr.microsoft.com/playwright/python:v1.40.0-jammy`
  - `PYTHONUNBUFFERED`, `PIP_NO_CACHE_DIR` 최적화
  - 의존성 레이어 캐시 (requirements.txt 먼저 복사)
  - `/data` 볼륨 + `SETTINGS_DIR=/data` 환경변수
  - `EXPOSE 8000`, `CMD ["python", "main.py"]`

- [x] **`docker-compose.yml`** 신규 생성
  - `restart: unless-stopped`
  - `shm_size: "256mb"` (단일 Chromium 인스턴스)
  - `./data:/data` 볼륨 마운트
  - `HOST`/`PORT`/`SETTINGS_DIR` 환경변수

- [x] **`.dockerignore`** 신규 생성 — `.git`, `.venv`, `__pycache__`, `mockups/`, `*.md` 등 제외 (이미지 크기 축소)

- [x] **`.env.example`** 신규 생성 — `SETTINGS_DIR`, `HOST`, `PORT`

- [x] **`gui.py`** 삭제

- [x] **`.github/workflows/build-exe.yml`** 삭제 — Windows EXE 빌드 워크플로는 웹 버전에 불필요

---

## Phase 5: Oracle Cloud 배포

- [ ] Oracle Cloud 계정 생성 및 Free Tier VM 생성
  - Shape: `VM.Standard.A1.Flex` (ARM Free Tier, 1 OCPU / 6GB 충분)
  - Image: Ubuntu 22.04
  - 공용 IP 할당, SSH 키 등록

- [ ] Security List에서 포트 개방
  - Oracle Cloud Security List: TCP 22, 80, 8000
  - Ubuntu iptables: 포트 8000 허용 + 저장

- [ ] VM에 Docker 설치

- [ ] 앱 클론 + 빌드 + 실행
  ```bash
  git clone https://github.com/JYKil/YeonsuBot-Web /opt/yeonsubot
  cd /opt/yeonsubot && mkdir -p data
  docker compose up -d --build
  ```

### Oracle Cloud Free Tier VM 생성 가이드

#### 1. 계정 생성

URL: https://www.oracle.com/kr/cloud/free/

1. "무료로 시작하기" (Start for free) 클릭
2. 이메일 입력 → 국가 "대한민국" 선택 → 이메일 인증
3. 계정 정보 입력 (이름, 주소)
4. 휴대폰 SMS 인증 (필수)
5. 결제 카드 등록 (필수, 해외결제 가능 카드 — 본인 인증용 $0 또는 ₩100 임시 승인. Always Free 리소스만 쓰면 과금 없음)
6. 홈 리전 선택 — **Korea Central (Seoul)** 권장 (한 번 정하면 변경 불가)
7. 계정 생성 완료 (5~10분 프로비저닝)

> 팁: 카드 인증에서 자주 실패하면 VPN 끄고, 신한/KB 체크카드보다 삼성/현대 신용카드가 성공률이 높습니다.

#### 2. VM (Compute Instance) 생성

로그인 후 OCI 콘솔: https://cloud.oracle.com/

**2-1. 인스턴스 생성 화면 진입**

좌상단 햄버거 메뉴 → Compute → Instances → Create instance

**2-2. 주요 설정**

| 항목 | 값 |
|---|---|
| Name | `yeonsu-bot` |
| Compartment | (root 그대로) |
| Placement (AD) | 기본값 |
| Image | **Canonical Ubuntu 22.04** (Change image에서 선택) |
| Shape | **Ampere — VM.Standard.A1.Flex** (ARM, Always Free)<br>OCPU: 2~4, Memory: 12~24 GB (총 4 OCPU / 24 GB 무료) |
| Network | 기본 VCN 자동 생성 허용 |
| Public IP | Assign a public IPv4 address ✅ |
| SSH keys | **Generate a key pair for me** → **Save private key** (.key 파일 꼭 다운로드, 재발급 불가) |
| Boot volume | 기본 46.6 GB (무료 200 GB까지 가능) |

> ⚠️ Ampere A1 용량 부족(Out of capacity) 에러가 자주 납니다. 나오면 **다른 AD로 바꿔서** 또는 **10~30분 후 재시도**. 정 안 되면 Shape을 **VM.Standard.E2.1.Micro** (AMD, 1 OCPU / 1 GB)로 대체 — Docker 돌리기엔 빡빡하지만 이 봇 정도는 가능.

Create 클릭 → 1~2분 후 RUNNING 상태가 되면 Public IP 확인.

#### 3. 접속 및 방화벽

##### 3-1. SSH 키 다루기

VM 생성 시 다운로드 받은 키 파일은 보통 두 개입니다:

- `ssh-key-YYYY-MM-DD.key` — **private key** (열쇠, 절대 유출 금지)
- `ssh-key-YYYY-MM-DD.key.pub` — **public key** (자물쇠, 백업용)

> ⚠️ private key는 **다운로드 시점 한 번만** 받을 수 있습니다. 잃어버리면 VM 재생성 필요.

**(1) 안전한 위치로 이동 + 이름 정리**

```bash
mkdir -p ~/.ssh
mv ~/Downloads/ssh-key-YYYY-MM-DD.key ~/.ssh/oracle_yeonsubot
mv ~/Downloads/ssh-key-YYYY-MM-DD.key.pub ~/.ssh/oracle_yeonsubot.pub
```

**(2) 권한 설정 (필수)**

권한이 너무 열려있으면 SSH가 사용을 거부합니다 (`UNPROTECTED PRIVATE KEY FILE!` 에러).

```bash # 본인만 읽기/쓰기 # 본인 읽기/쓰기, 남들 읽기만
chmod 600 ~/.ssh/oracle_yeonsubot       
chmod 644 ~/.ssh/oracle_yeonsubot.pub   
```

**(3) VM 접속 테스트**

OCI 콘솔에서 Public IP 확인 후:

```bash
ssh -i ~/.ssh/oracle_yeonsubot ubuntu@<Public-IP>
```

- `-i` : 사용할 private key 지정
- `ubuntu` : Ubuntu 이미지 기본 사용자명 (Oracle Linux면 `opc`)
- 첫 접속 시 `Are you sure you want to continue connecting?` → **yes**

**(4) (선택) `~/.ssh/config` 별칭 설정**

매번 `-i` 옵션 안 쓰게 별칭 등록:

```bash
cat >> ~/.ssh/config <<'EOF'
Host yeonsubot
  HostName <Public-IP>
  User ubuntu
  IdentityFile ~/.ssh/oracle_yeonsubot
EOF
chmod 600 ~/.ssh/config
```

이후엔 `ssh yeonsubot` 만 입력하면 접속됩니다.

> 💡 백업: private key를 잃어버리면 복구 불가. 1Password / iCloud Keychain / 외장 드라이브 등에 백업 권장. **절대 git에 커밋 금지** — `.gitignore`에 `*.key`, `id_*` 추가.

##### 3-2. 포트 개방

**포트 열기 (8000번 — FastAPI)** — 두 군데 모두 열어야 접속됩니다:

1. **OCI 콘솔 Security List**: Networking → Virtual Cloud Networks → (VCN) → Subnet → Default Security List → Add Ingress Rule
   - Source CIDR: `0.0.0.0/0`, Destination Port: `8000`
2. **VM 내부 iptables** (Ubuntu는 기본 차단):
   ```bash
   sudo iptables -I INPUT 6 -m state --state NEW -p tcp --dport 8000 -j ACCEPT
   sudo netfilter-persistent save
   ```

#### 4. Docker 설치 후 배포

```bash
sudo apt update && sudo apt install -y docker.io docker-compose-v2 git
sudo usermod -aG docker ubuntu && newgrp docker
git clone <your-repo> && cd YeonsuBot-Web
docker compose up -d --build
```

접속: `http://<Public-IP>:8000`

---

## Phase 6: 검증

### 로컬 REST + WS Smoke (2026-04-14, ✅)

로컬에서 `uv run --with fastapi --with 'uvicorn[standard]' --with playwright --with requests python main.py` 로 서버 기동 후 검증:

- [x] `GET /` → 200, index.html 렌더
- [x] `GET /api/status` → `{running: false, status: "중지"}` 초기 상태
- [x] `GET /api/settings` → DEFAULTS + 10개 facilities 반환
- [x] `POST /api/start` (빈 body) → **400** "아이디를 입력하세요"
- [x] `POST /api/start` (정상 payload) → **200**, `running: true`, `target: "속초수련원 2026-06-01~2026-06-02"`, `status: "로그인 중..."`
- [x] 중복 `POST /api/start` → **409** "이미 실행 중입니다" (인라인 토스트 동작 검증)
- [x] `POST /api/stop` → 200, `running: false`, 실패 경로 `last_result: LOGIN_ERROR` 기록
- [x] WS `/ws` 연결 → 5개 로그 즉시 재수신 (log_buffer 복원 검증)
- [x] 시스템 Chrome 감지 로그 확인 → `--no-sandbox` 미적용 (Phase 1-3 + `/review` 조건부 수정 검증)
- [x] lifespan shutdown → 워커 스레드 graceful join 검증

### UI 시각 확인 ✅

- [x] 브라우저로 `http://localhost:8000` 접속 후 레이아웃 확인
- [x] 첫 로드: 빈 상태 안내 표시 확인
- [x] 설정 입력 → [시작] → 버튼 spinner → 대상 보조 라인 표시 확인
- [x] 비밀번호 표시/숨김 토글 확인
- [x] 로그 위로 스크롤 → autoscroll pause + "↓ 새 로그 N건" 버튼 확인
- [x] 예약 성공 시뮬레이션 → "예약완료" 뱃지 + 자동 중지 → 재시작 시 뱃지 → 일반 상태 복귀 (idempotent 렌더 검증)
- [x] 키보드 Tab → focus ring + 의도된 순서 확인
- [x] 모바일 viewport (375px, Chrome DevTools) → 세로 스택 + 로그 영역 240px 이상 확인

### 사용 중 발견된 개선 사항 ✅

초기 구현 후 실사용하면서 다음 항목을 추가/수정했음 (각 항목 커밋 있음):

- [x] 체크인/체크아웃 기본값: 오늘/내일 자동 (로컬 타임존)
- [x] 체크인 변경 시 체크아웃 항상 +1일로 덮어쓰기
- [x] 저장된 과거 날짜는 무시하고 오늘/내일 폴백
- [x] 점검 주기 기본값 1분
- [x] 상태 뱃지 보조 라인 간결화 — "대상: ..." 만 표시 (마지막/다음 확인 시각은 로그로 충분)
- [x] START/STOP 버튼을 폼 마지막 (점검 주기 아래) 로 이동
- [x] "로그 지우기" 버튼 + `POST /api/logs/clear` 엔드포인트 + WS `clear` 브로드캐스트 (다중 탭 동기화)
- [x] 스케줄러 시작 시 기존 로그 자동 초기화 (`api_start` 에서 buffer clear)
- [x] 사이클 간 시각적 구분자 — `scheduler.on_cycle_start` 콜백 + 2번째 사이클부터 점선 separator 삽입
- [x] 예약 성공 뱃지 렌더링을 idempotent 하게 재작성 (statusLabel/statusBadge 형제 hidden 토글 방식)
- [x] `--no-sandbox` 는 내장 Chromium 에서만 적용 (로컬 macOS/Windows 시스템 Chrome 샌드박스 유지)

### Docker & 배포

- [x] Docker: 로컬 macOS (Docker Desktop) 에서 `docker compose up --build` 정상 동작 확인
- [ ] Oracle Cloud VM에서 `http://<공용IP>:8000` 접속 확인
