# YeonsuBot 웹 전환 계획

## 개요
CustomTkinter 데스크톱 앱을 FastAPI + WebSocket + HTML 웹 앱으로 전환한다.
**본인 1명 전용**, 한 번에 한 세션만 돌리는 단일 슬롯 구조. 브라우저로 접속해 로컬 설치 없이 사용하고, Oracle Cloud Free Tier VM에 Docker로 배포한다.

**핵심 원칙**: 비즈니스 로직(`checker.py`, `scheduler.py`, `notifier.py`, `facilities.py`, `config.py`)은 GUI 의존성이 없으므로 **거의 그대로 재사용**. GUI 레이어만 교체.

---

## 최종 파일 구조

```
YeonsuBot-Web/
├── main.py                  ← FastAPI 진입점으로 교체
├── web_server.py            ← FastAPI 앱 (AppState, /ws, lifespan)
├── checker.py               ← headless 폴백 + --no-sandbox 수정
├── scheduler.py             ← 변경 없음
├── notifier.py              ← 변경 없음
├── config.py                ← SETTINGS_DIR 환경변수만 추가
├── facilities.py            ← 변경 없음
├── templates/
│   └── index.html           ← 단일 패널 UI (Vanilla JS)
├── requirements.txt         ← fastapi, uvicorn 추가 / GUI 패키지 제거
├── Dockerfile
├── docker-compose.yml
├── .env.example
└── gui.py                   ← 삭제
```

---

## 아키텍처

### 단일 슬롯 구조

```
AppState
├── scheduler: MonitorScheduler
├── ws_clients: set[WebSocket]
├── log_buffer: deque(maxlen=200)
└── current_status: str
```

**데이터 플로우:**
```
브라우저
  └── WS /ws ←── AppState 로그/상태 스트리밍

POST /api/start  → AppState.scheduler.start()
POST /api/stop   → AppState.scheduler.stop()
GET  /api/status → {running, status, last_result}
```

### 백엔드 (FastAPI)

**WebSocketLogHandler** — Python `logging.Handler` 상속
- `emit()` 안에서 `loop.call_soon_threadsafe()`로 워커 스레드 → asyncio 루프 안전하게 전달
- 앱 시작 시 루트 로거에 1회 등록

**lifespan** — 앱 종료 시 `scheduler.stop()` + `join(timeout=15)`

### REST 엔드포인트

| Method | Path | 설명 |
|--------|------|------|
| `GET`  | `/` | index.html 반환 |
| `GET`  | `/api/status` | `{running, status, last_result}` 반환 |
| `GET`  | `/api/settings` | settings 로드 (비밀번호 마스킹) |
| `POST` | `/api/start` | 설정 저장 + `scheduler.start()`. 이미 실행 중이면 409 |
| `POST` | `/api/stop` | `scheduler.stop()` |
| `POST` | `/api/slack/test` | Slack 웹훅 테스트 메시지 |

### WebSocket

**엔드포인트**: `WS /ws`

- 연결 시 `log_buffer` 즉시 전송 (재연결/새 탭 대응)
- 서버 → 클라이언트 메시지:
  ```json
  {"type": "log",    "message": "10:05:28 [INFO] 로그인 중..."}
  {"type": "status", "status": "모니터링 중"}
  {"type": "result", "result": "SUCCESS", "detail": "20241201"}
  ```

### 프론트엔드 (단일 패널, Vanilla JS)

```
┌──────────────────────────────────────────────────────────┐
│  YeonsuBot                                                │  ← 다크 nav (rgba(0,0,0,0.8) + blur)
├─────────────────────────┬────────────────────────────────┤
│  설정 패널 (40%)         │  로그 뷰어 (60%)               │
│                          │                                │
│  ● 실행중                │  2024-04-24 09:02:44 booking  │
│                          │  2024-04-24 09:02:42 attempt  │
│  연수원: 신구로 연수원    │  2024-04-24 09:00:32 checking │
│  체크인: 2024-05-01      │  2024-04-24 09:00:02 success  │
│  체크아웃: 2024-05-02    │                                │
│  점검주기: 2분           │  (어두운 배경 #1d1d1f,        │
│                          │   모노스페이스, 자동 스크롤)   │
│  [      STOP      ]      │                                │
└─────────────────────────┴────────────────────────────────┘
```

**디자인 시스템 토큰** (DESIGN.md Apple 시스템 적용):

| 요소 | 값 |
|------|-----|
| 페이지 배경 | `#f5f5f7` |
| 네비게이션 | `rgba(0,0,0,0.8)` + `backdrop-filter: blur(20px)` |
| 설정 패널 배경 | `#ffffff` |
| 로그 뷰어 배경 | `#1d1d1f` (Dark Surface 1) |
| 로그 텍스트 | `#ffffff`, 13px monospace |
| 시작 버튼 | `#0071e3` bg, white text, 8px radius |
| 중지 버튼 | `#1d1d1f` bg, white text, 8px radius |
| 카드 shadow | `rgba(0,0,0,0.22) 3px 5px 30px` |
| 폰트 | SF Pro Text (fallback: Helvetica Neue, Arial) |

**상태 표시** (색 + 텍스트 동시 — 접근성):

| 상태 | 표시 |
|------|------|
| 실행중 | 초록 dot + "실행중" |
| 중지 | 회색 dot + "중지" |
| 예약완료 | `#0071e3` badge + "예약완료 YYYY.MM.DD" |
| 오류 | 빨간 dot + "오류 발생" |
| 예약 시도중 | 파란 dot (애니메이션) + "예약 시도 중..." |

**상호작용 상태:**

| 기능 | LOADING | EMPTY | ERROR | SUCCESS |
|------|---------|-------|-------|---------|
| 봇 상태 | gray dot + spinning | — | 빨간 dot + 텍스트 | 초록 dot |
| 로그 뷰어 | "연결 중..." | "로그가 없습니다" | "연결 끊김. 재시도 중..." | 스트리밍 |
| 설정 폼 | 버튼 disabled | 기본값 placeholder | 인라인 오류 | 실행 시작 |

**동작 규칙:**
- 예약 성공 시 **자동 중지** + "예약완료" badge (중복 예약 방지)
- 페이지 로드 시 `GET /api/status` → 현재 상태 동기화
- WS 끊김 시 3초 후 자동 재연결 + `log_buffer` 즉시 수신
- 이미 실행 중인 상태에서 `/api/start` 호출 시 409 반환

**반응형:**
- Desktop (1070px+): 설정 40% + 로그 60%
- Tablet (640-1070px): 설정 패널 축소
- Mobile (< 640px): 설정/로그 세로 스택

**접근성:**
- 상태 뱃지: `aria-label`, `role="status"`
- 로그 영역: `aria-live="polite"`
- 모든 버튼 최소 44px 터치 타겟

---

## 주요 코드 변경 사항

### `checker.py` — headless 폴백
```python
def _detect_browser_channel() -> str | None:
    # 못 찾으면 None 반환 (내장 Chromium 폴백)
    return None

# BrowserSession.start():
channel = _detect_browser_channel()
launch_kwargs = {
    "headless": True,
    "args": ["--no-sandbox", "--disable-dev-shm-usage"],
}
if channel:
    launch_kwargs["channel"] = channel
self._browser = self._pw.chromium.launch(**launch_kwargs)
```

### `config.py` — Docker 볼륨만 지원 (최소 변경)
```python
import os

base_dir = os.environ.get("SETTINGS_DIR", os.path.dirname(os.path.abspath(__file__)))
SETTINGS_FILE = os.path.join(base_dir, "settings.json")

# load() / save() 시그니처 변경 없음
```

### `notifier.py`
**변경 없음.**

### `scheduler.py`, `facilities.py`
**변경 없음.**

---

## Docker 구성

### `Dockerfile`
```dockerfile
FROM mcr.microsoft.com/playwright/python:v1.40.0-jammy

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .

VOLUME ["/data"]
ENV SETTINGS_DIR=/data

EXPOSE 8000
CMD ["python", "main.py"]
```

### `docker-compose.yml`
```yaml
services:
  yeonsubot:
    build: .
    restart: unless-stopped
    ports:
      - "8000:8000"
    volumes:
      - ./data:/data
    environment:
      - SETTINGS_DIR=/data
    shm_size: "256mb"   # 단일 Chromium 인스턴스
```

---

## Oracle Cloud 배포

### VM 생성
- Shape: `VM.Standard.A1.Flex` (ARM Free Tier, 1 OCPU / 6GB 충분)
- Image: Ubuntu 22.04
- 공용 IP 할당

### 방화벽 설정 (두 곳 모두)
1. Oracle Cloud Security List: TCP 22, 80, 8000 허용
2. Ubuntu iptables:
   ```bash
   sudo iptables -I INPUT 6 -m state --state NEW -p tcp --dport 8000 -j ACCEPT
   sudo netfilter-persistent save
   ```

### 배포
```bash
sudo apt update && sudo apt install -y docker.io docker-compose-plugin
sudo usermod -aG docker ubuntu && newgrp docker

git clone https://github.com/JYKil/yeonsu-bot /opt/yeonsubot
cd /opt/yeonsubot
mkdir -p data
docker compose up -d --build
```

접속: `http://<Oracle-VM-공용-IP>:8000`

---

## NOT in scope
- 다중 슬롯/다중 계정 동시 실행 (1슬롯 고정)
- 웹 인증/로그인 기능 (본인 전용 전제)
- HTTPS 자동 설정
- 동시 접속 충돌 방지 (한 번에 한 사람이 쓴다는 전제 — 여러 탭에서 start 호출 시 409 반환으로 충분)

---

## 검증
1. `docker compose up -d` 후 `http://localhost:8000` 접속
2. 설정 입력 → [시작] → 로그 "로그인 중..." → "모니터링 중" 확인
3. [중지] → 상태 "중지됨" 확인
4. [Slack 테스트] → 웹훅 메시지 수신 확인
5. 페이지 새로고침 → 상태 및 로그 버퍼 복원 확인
6. 실행 중 `/api/start` 재호출 → 409 확인
7. Oracle Cloud VM 동일 절차 반복
