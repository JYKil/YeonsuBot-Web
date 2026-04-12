# YeonsuBot 웹 전환 계획

## 개요
CustomTkinter 데스크톱 앱을 FastAPI + WebSocket + HTML 웹 앱으로 전환한다.
친구 소수가 로컬 설치 없이 브라우저로 접속해 사용할 수 있으며, **최대 3개 계정을 각각 독립 슬롯으로 동시 실행** 가능하다. Oracle Cloud Free Tier VM에 Docker로 배포한다.

**핵심 원칙**: 비즈니스 로직(`checker.py`, `scheduler.py`, `notifier.py`, `facilities.py`)은 GUI 의존성이 없으므로 그대로 재사용. GUI 레이어만 교체.

---

## 최종 파일 구조

```
YeonsuBot-Web/
├── main.py                  ← FastAPI 진입점으로 교체
├── web_server.py            ← FastAPI 앱 (SlotState×3, /ws/{slot_id}, lifespan)
├── checker.py               ← headless 폴백 + --no-sandbox 수정
├── scheduler.py             ← 변경 없음
├── notifier.py              ← slot_label 선택 파라미터 추가
├── config.py                ← SETTINGS_DIR 환경변수 + load(slot_id)/save(slot_id)
├── facilities.py            ← 변경 없음
├── templates/
│   └── index.html           ← 탭 UI (슬롯 3개, Vanilla JS)
├── requirements.txt         ← fastapi, uvicorn 추가 / GUI 패키지 제거
├── Dockerfile
├── docker-compose.yml
├── .env.example
└── gui.py                   ← 삭제
```

---

## 아키텍처

### 다중 슬롯 구조

```
AppState
├── slots[0]: SlotState
├── slots[1]: SlotState
└── slots[2]: SlotState

SlotState
├── scheduler: MonitorScheduler  (독립 인스턴스)
├── ws_clients: set[WebSocket]   (/ws/0, /ws/1, /ws/2)
├── log_buffer: deque(maxlen=200)
└── current_status: str
```

**데이터 플로우:**
```
브라우저
  ├── WS /ws/0 ←── slots[0] 로그/상태
  ├── WS /ws/1 ←── slots[1] 로그/상태
  └── WS /ws/2 ←── slots[2] 로그/상태
  
POST /api/0/start → slots[0].scheduler.start()
GET  /api/status  → [{slot:0,...}, {slot:1,...}, {slot:2,...}]
```

### 백엔드 (FastAPI)

**WebSocketLogHandler** — Python `logging.Handler` 상속
- `emit()` 안에서 `loop.call_soon_threadsafe()`로 워커 스레드 → asyncio 루프 안전하게 전달
- 슬롯 초기화 시 각 슬롯별 별도 핸들러 등록

**lifespan** — 앱 종료 시 3개 슬롯 `scheduler.stop()` + join(timeout=15)

### REST 엔드포인트

| Method | Path | 설명 |
|--------|------|------|
| `GET` | `/` | index.html 반환 |
| `GET` | `/api/status` | 슬롯 3개 상태 배열 반환 |
| `GET` | `/api/settings/{slot_id}` | 해당 슬롯 settings 로드 (비밀번호 마스킹) |
| `POST` | `/api/{slot_id}/start` | 설정 저장 + scheduler.start(). 실행 중이면 409 |
| `POST` | `/api/{slot_id}/stop` | 해당 슬롯 scheduler.stop() |
| `POST` | `/api/{slot_id}/slack/test` | 해당 슬롯 Slack 테스트 |

### WebSocket

**엔드포인트**: `WS /ws/{slot_id}` (0, 1, 2 각각)

- 연결 시 해당 슬롯의 `log_buffer` 즉시 전송 (재연결/새 탭 대응)
- 서버 → 클라이언트 메시지:
  ```json
  {"type": "log",    "message": "10:05:28 [INFO] 로그인 중..."}
  {"type": "status", "status": "모니터링 중"}
  {"type": "result", "result": "SUCCESS", "detail": "20241201"}
  ```

### 프론트엔드 (탭 UI, Vanilla JS)

**승인된 레이아웃** (2026-04-13 디자인 리뷰 확정):

```
┌──────────────────────────────────────────────────────────┐
│  YeonsuBot                               [+ 봇 추가]     │  ← 다크 nav (rgba(0,0,0,0.8) + blur)
├──────────────────────────────────────────────────────────┤
│  [봇 1 — user@email.com]  [봇 2]  [봇 3]                 │  ← 탭 바, 활성: #0071e3 언더라인
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
| 활성 탭 인디케이터 | `#0071e3` (Apple Blue), 2px underline |
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

**상호작용 상태 (모든 기능):**

| 기능 | LOADING | EMPTY | ERROR | SUCCESS |
|------|---------|-------|-------|---------|
| 탭 목록 | — | "봇이 없습니다 + CTA" | — | 탭 표시 |
| 봇 상태 | gray dot + spinning | — | 빨간 dot + 텍스트 | 초록 dot |
| 로그 뷰어 | "연결 중..." | "로그가 없습니다" | "연결 끊김. 재시도 중..." | 스트리밍 |
| 봇 추가 폼 | 버튼 disabled | 빈 폼 placeholder | 인라인 오류 | 탭에 추가됨 |

**동작 규칙:**
- 예약 성공 시 봇 **자동 중지** + "예약완료" badge (중복 예약 방지)
- 탭 전환 시에도 3개 WS 연결 유지 (탭 레이블에 실행 중 ● 표시)
- 페이지 로드 시 `GET /api/status` → 3개 슬롯 상태 동기화
- WS 끊김 시 3초 후 자동 재연결 + log_buffer 즉시 수신
- 빈 상태 (봇 0개): "아직 봇이 없습니다 / + 봇 추가" 중앙 안내

**반응형:**
- Desktop (1070px+): 설정 40% + 로그 60%, 수평 탭 바
- Tablet (640-1070px): 설정 패널 축소, 탭 바 유지
- Mobile (< 640px): 탭 수평 스크롤, 설정/로그 세로 스택

**접근성:**
- 탭: `role="tablist"`, `role="tab"`, `aria-selected`
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

### `config.py` — 슬롯별 설정 + Docker 볼륨
```python
import os

MAX_SLOTS = 3
base_dir = os.environ.get("SETTINGS_DIR", os.path.dirname(os.path.abspath(__file__)))

def load(slot_id: int = 0) -> dict:
    # settings_{slot_id}.json 로드, 없으면 DEFAULTS 반환

def save(slot_id: int, settings: dict) -> None:
    # settings_{slot_id}.json 저장
```

### `notifier.py` — 슬롯 식별 추가
```python
def send_booking_success(username, facility, checkin, checkout, slot_label=None):
    prefix = f"[{slot_label}] " if slot_label else ""
    # 메시지에 prefix 추가 (예: "[Slot 1] 홍길동으로 예약 성공!")
```

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
    shm_size: "512mb"   # 3개 슬롯 동시 Chromium 실행 시 필요
```

---

## Oracle Cloud 배포

### VM 생성
- Shape: `VM.Standard.A1.Flex` (ARM Free Tier, 2 OCPU / 12GB 권장)
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
- 슬롯별 다른 Slack 웹훅 URL (모든 슬롯 동일 웹훅)
- 슬롯 이름 커스터마이징 ("슬롯 1/2/3" 고정)
- 슬롯 4개 이상
- 웹 인증/로그인 기능
- HTTPS 자동 설정 (선택 사항)

---

## 검증
1. `docker compose up -d` 후 `http://localhost:8000` 접속
2. 슬롯 1 탭 → 설정 입력 → [시작] → 로그 "로그인 중..." → "모니터링 중" 확인
3. 슬롯 2 탭 → 다른 계정으로 동시 실행 → 각 로그 독립 표시 확인
4. [중지] → 상태 "중지됨" 확인
5. [Slack 테스트] → "[Slot 1] ..." 형식 메시지 수신 확인
6. 페이지 새로고침 → 3개 슬롯 상태 및 로그 버퍼 복원 확인
7. Oracle Cloud VM 동일 절차 반복
