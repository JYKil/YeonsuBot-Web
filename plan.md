# YeonsuBot 웹 전환 계획

## 진행 상황 (2026-04-14)

| Phase | 상태 | 비고 |
|---|---|---|
| 선행 — `/plan-eng-review` | ✅ 완료 | 3슬롯 → 1슬롯 스코프 축소 |
| 선행 — `/plan-design-review` | ✅ 완료 | 6.5 → 9.2/10, 목업 + 디자인 토큰 확정 |
| Phase 1 — 핵심 로직 (config/checker) | ✅ 완료 | `ed2a137` |
| Phase 2 — FastAPI 백엔드 (web_server/main) | ✅ 완료 | `ed2a137` |
| Phase 3 — 프론트엔드 (templates/index.html) | ✅ 완료 | `ed2a137` |
| 선행 — `/review` (pre-landing) | ✅ 완료 | P2 버그 2개 수정 `4a9890c` |
| Phase 4 — 패키지 & Docker | ✅ 완료 | Dockerfile + docker-compose.yml + .dockerignore + .env.example, gui.py & build-exe.yml 삭제 |
| Phase 5 — Oracle Cloud 배포 | ⬜ 대기 | 실제 VM 작업 필요 |
| Phase 6 — 로컬 검증 | ✅ 완료 | REST smoke + WS + UI 시각 (데스크톱 + 모바일 DevTools) |

작업 세부는 `to-do.md`, 디자인 목업은 `mockups/index.html` 참조.

---

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
├── checker.py               ← Docker: Google Chrome + --no-sandbox 수정
├── scheduler.py             ← 변경 없음
├── notifier.py              ← 변경 없음
├── config.py                ← SETTINGS_DIR 환경변수만 추가
├── facilities.py            ← 변경 없음
├── templates/
│   └── index.html           ← 단일 패널 UI (Vanilla JS)
├── mockups/
│   └── index.html           ← 정적 디자인 목업 (참고용, 실제 앱 아님)
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
├── current_status: str
└── last_check_at: datetime | None
```

**데이터 플로우:**
```
브라우저
  └── WS /ws ←── AppState 로그/상태 스트리밍

POST /api/start  → AppState.scheduler.start()
POST /api/stop   → AppState.scheduler.stop()
GET  /api/status → {running, status, last_check_at, next_check_at, target}
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
| `GET`  | `/api/status` | `{running, status, last_check_at, next_check_at, target}` 반환 |
| `GET`  | `/api/settings` | settings 로드 (비밀번호 마스킹) |
| `POST` | `/api/start` | 설정 저장 + `scheduler.start()`. 이미 실행 중이면 409 |
| `POST` | `/api/stop` | `scheduler.stop()` |
| `POST` | `/api/slack/test` | Slack 웹훅 테스트 |

### WebSocket

**엔드포인트**: `WS /ws`

- 연결 시 `log_buffer` 즉시 전송 (재연결/새 탭 대응)
- 서버 → 클라이언트 메시지:
  ```json
  {"type": "log",    "message": "10:05:28 [INFO] 로그인 중..."}
  {"type": "status", "status": "모니터링 중", "last_check_at": "09:23", "next_check_at": "09:25"}
  {"type": "result", "result": "SUCCESS", "detail": "20241201"}
  ```

---

## 프론트엔드 (단일 패널, Vanilla JS)

### 정보 계층 (시선 1→2→3 순서)

1. **상태 뱃지 + 액션 버튼** — "지금 돌아가는지, 나는 뭘 누르면 되는지"
2. **설정 폼** — "뭘 노리고 있는지"
3. **로그 뷰어** — "지금까지 뭐 했는지"

이 순서대로 액션 버튼을 폼 **위**에 배치한다.

### 레이아웃

```
┌──────────────────────────────────────────────────────────┐
│  YeonsuBot                                                │  ← 다크 nav (rgba(0,0,0,0.8) + blur)
├─────────────────────────┬────────────────────────────────┤
│  ● 모니터링 중           │  09:02:44  booking attempt    │
│  마지막: 09:23           │  09:02:42  attempting...      │
│  다음: 09:25             │  09:00:32  checking 5/01      │
│  대상: 신구로 5/1~5/2     │  09:00:02  login success      │
│  [      STOP      ]      │                                │
│  ──────────────────      │  (#1d1d1f, SF Mono 13px,      │
│  아이디: hong.gildong    │   자동 스크롤)                 │
│  비밀번호: ••••••• [표시]│                                │
│  연수원: 신구로 연수원    │                                │
│  체크인: 2024-05-01      │                                │
│  체크아웃: 2024-05-02    │                                │
│  점검주기: 2분           │                                │
│  [Slack 테스트]          │                                │
└─────────────────────────┴────────────────────────────────┘
   설정 패널 (40%, flat)        로그 뷰어 (60%, flat)
```

**시작/중지 버튼은 같은 자리에서 토글.** 실행 상태에 따라 START 또는 STOP 둘 중 하나만 노출.

### 디자인 시스템 토큰

#### 1. Color (DESIGN.md 매핑)

| 요소 | 값 |
|------|-----|
| 페이지 배경 | `#f5f5f7` |
| 네비게이션 | `rgba(0,0,0,0.8)` + `backdrop-filter: saturate(180%) blur(20px)` |
| 설정 패널 배경 | `#ffffff` |
| 로그 뷰어 배경 | `#1d1d1f` (Dark Surface 1) |
| 본문 텍스트 (light) | `#1d1d1f` |
| 보조 텍스트 (light) | `rgba(0, 0, 0, 0.8)` |
| 로그 텍스트 | `#ffffff` |
| 시작 버튼 | bg `#0071e3`, text `#ffffff` |
| 중지 버튼 | bg `#1d1d1f`, text `#ffffff` |
| Focus ring | `2px solid #0071e3` |
| 상태 dot — 실행중 | `#34c759` (Apple Green, 시스템 색) |
| 상태 dot — 중지 | `rgba(0, 0, 0, 0.48)` |
| 상태 dot — 오류 | `#ff3b30` (Apple Red, 시스템 색) |
| 예약완료 badge | `#0071e3` bg, `#ffffff` text |

> **Shadow 사용 안 함.** 설정 패널·로그 뷰어 모두 flat. DESIGN.md "shadow는 거의 안 씀" 원칙. 깊이 분리는 배경색 대비(`#ffffff` ↔ `#1d1d1f`)로만 한다.

#### 2. Typography (DESIGN.md 행 매핑)

| 요소 | DESIGN.md 행 | 사양 |
|------|---|---|
| nav 제목 "YeonsuBot" | Body Emphasis | SF Pro Text · 17px · 600 · line-height 1.24 · letter-spacing -0.374px |
| 상태 뱃지 텍스트 ("모니터링 중") | Body Emphasis | SF Pro Text · 17px · 600 · 1.24 · -0.374px |
| 보조 라인 ("마지막: 09:23 …") | Caption | SF Pro Text · 14px · 400 · 1.29 · -0.224px |
| 폼 라벨 ("아이디", "비밀번호", "연수원" …) | Caption Bold | SF Pro Text · 14px · 600 · 1.29 · -0.224px |
| 폼 입력값 (아이디/비번 포함) | Body | SF Pro Text · 17px · 400 · 1.47 · -0.374px |
| 비번 표시/숨김 토글 텍스트 | Caption Bold | SF Pro Text · 14px · 600 · `#0071e3` |
| 시작/중지 버튼 텍스트 | Button | SF Pro Text · 17px · 400 · line-height 1.0 (상하 padding으로 높이 확보) |
| 로그 본문 | (신규) | SF Mono · 13px · 400 · 1.5 |
| 로그 타임스탬프 | Micro | SF Mono · 12px · 400 · 1.33 · -0.12px (`rgba(255,255,255,0.6)`) |
| 예약완료 badge | Caption Bold | SF Pro Text · 14px · 600 · 1.29 · -0.224px |

폰트 fallback: `"SF Pro Text", -apple-system, BlinkMacSystemFont, "Helvetica Neue", Helvetica, Arial, sans-serif` / 모노: `"SF Mono", Menlo, Monaco, "Courier New", monospace`

#### 3. Spacing & Radius (DESIGN.md 8px base)

| 토큰 | 값 | 사용처 |
|---|---|---|
| `space-1` | 4px | 인라인 미세 갭 (dot ↔ 텍스트) |
| `space-2` | 8px | 폼 라벨 ↔ 입력 |
| `space-3` | 12px | 인풋 내부 padding-y |
| `space-4` | 16px | 폼 행 간격, 카드 내부 좌우 padding |
| `space-5` | 24px | 섹션 간격 (액션 ↔ 폼 구분선) |
| `space-6` | 32px | 패널 내부 외곽 padding |
| `radius-input` | 11px | 폼 인풋, Slack 테스트 버튼 |
| `radius-button` | 8px | 시작/중지 버튼, 예약완료 badge |
| `radius-dot` | 50% | 상태 dot |
| `radius-pill` | 980px | (현재 미사용, 향후 inline CTA용) |

### 상태 표시 (색 + 텍스트 동시 — 접근성)

| 상태 | 표시 |
|------|------|
| 실행중 | `#34c759` dot + "모니터링 중" + 보조 라인 |
| 중지 | `rgba(0,0,0,0.48)` dot + "중지" |
| 예약완료 | `#0071e3` badge + "예약완료 YYYY.MM.DD" |
| 오류 | `#ff3b30` dot + "오류 발생" + 1줄 사유 |
| 예약 시도중 | `#0071e3` dot (1.6s pulse) + "예약 시도 중..." |

> **Reduced motion**: `@media (prefers-reduced-motion: reduce)` 시 pulse 애니메이션 정적 dot 으로 대체.

### 보조 정보 라인 (장시간 대기 UX 핵심)

상태 뱃지 바로 아래, 실행 중일 때만 표시:

```
마지막 확인: 09:23 · 다음 확인: 09:25 · 대상: 신구로 5/1~5/2
```

봇은 사용자가 페이지를 열어두고 수 시간 기다리는 시나리오가 90%다. 이 한 줄이 "살아있다"는 신뢰 신호이자 새로고침 욕구를 줄이는 가장 강한 레버.

### 인터랙션 상태 (모든 기능)

| 기능 | LOADING | EMPTY | ERROR | SUCCESS |
|------|---------|-------|-------|---------|
| 첫 로드 (설정 없음) | "불러오는 중..." 폼 disabled | 폼 placeholder + "위 항목을 입력하고 시작을 누르세요" 안내 | — | 저장된 값 자동 채움 |
| 봇 상태 | gray dot + spinning | — | 빨간 dot + 사유 1줄 | 초록 dot + 보조 라인 |
| 시작 버튼 | 버튼 disabled + 인라인 spinner ("시작 중...") | — | 인라인 토스트 ("이미 실행 중입니다" — 409) | 버튼이 STOP 으로 토글 |
| 로그 뷰어 | "연결 중..." | "로그가 없습니다" | "연결 끊김. 3초 후 재시도..." (인라인 상단 배너) | 스트리밍 |
| 로그 자동 스크롤 | — | — | — | 사용자가 위로 스크롤 시 autoscroll pause + 우하단 "↓ 새 로그 N건" 버튼 노출 |
| Slack 테스트 | 버튼 disabled + spinner | — | 인라인 토스트 (빨강, "전송 실패: <사유>") | 인라인 토스트 (초록, "전송 성공") · 3초 후 자동 사라짐 |
| 설정 폼 | — | placeholder | 인풋별 인라인 오류 메시지 | 실행 시작 |

### 사용자 저널 (감정 곡선)

| Step | 사용자 행동 | 감정 | plan 대응 |
|---|---|---|---|
| 1 | 페이지 첫 진입 | "어떻게 시작하지?" | 빈 상태 안내 + placeholder |
| 2 | 설정 입력 | "이거 맞나?" | 인풋별 검증 + 오류 인라인 |
| 3 | [시작] 클릭 | "되고 있나?" | 버튼 spinner + status "시작 중..." |
| 4 | 로그 흐르기 시작 | "오 살아있다" | 실시간 WS 스트리밍 |
| 5 | **장시간 대기 (수 시간)** | **"지금 뭐 함?"** | **보조 라인: 마지막/다음/대상 — UX 핵심** |
| 6 | 예약 성공 알림 | "와 됐다!" | 자동 중지 + "예약완료" badge + Slack 알림 |
| 7 | 다음에 또 옴 | "이전 설정 그대로?" | settings.json 영속, 폼 자동 채움 |

### 동작 규칙

- 시작/중지 버튼은 **같은 자리에서 토글** — 실행 중이면 STOP 만, 중지면 START 만
- 예약 성공 시 봇 **자동 중지** + "예약완료" badge (중복 예약 방지). 새 설정 입력 후 시작 누르면 badge 사라짐
- 페이지 로드 시 `GET /api/status` → 현재 상태 + 보조 라인 동기화
- WS 끊김 시 3초 후 자동 재연결 + `log_buffer` 즉시 수신
- 이미 실행 중인 상태에서 `/api/start` 호출 시 409 → 인라인 토스트
- 로그 자동 스크롤은 사용자가 위로 스크롤하면 일시정지, "↓ 새 로그" 버튼으로 재개

### 반응형

| Breakpoint | 레이아웃 |
|---|---|
| Desktop (1070px+) | 설정 40% + 로그 60% 좌우 분할 |
| Tablet (640-1070px) | 설정 패널 폭 축소 (320px 고정), 로그 나머지 |
| Mobile (< 640px) | 세로 스택. 설정 위 (auto), 로그 아래 (`min-height: 240px`, viewport 50%) |

### 접근성

- 상태 뱃지: `role="status"`, `aria-live="polite"`, `aria-label`에 색에 의존하지 않는 텍스트 ("모니터링 중, 마지막 확인 09:23")
- 로그 영역: `aria-live="polite"`, 사용자 스크롤 시 라이브 영역 일시 갱신 중단
- 모든 인터랙티브 요소: keyboard focus 시 `outline: 2px solid #0071e3; outline-offset: 2px`
- Tab 순서: START/STOP → 폼 인풋(아이디→비밀번호→비번 토글→연수원→체크인→체크아웃→점검주기) → Slack 테스트
- 비밀번호 인풋: `type="password"` 기본, 토글 버튼으로 `type="text"` 전환. `autocomplete="current-password"`. 토글 버튼 `aria-pressed` 상태 반영
- 아이디 인풋: `autocomplete="username"`
- 모든 버튼 최소 44px 터치 타겟 (padding 으로 확보)
- Color contrast 검증:
  - 로그 텍스트 `#ffffff` on `#1d1d1f` = **16.0:1** (AAA)
  - 시작 버튼 텍스트 `#ffffff` on `#0071e3` = **4.6:1** (AA)
  - 본문 `#1d1d1f` on `#ffffff` = **17.4:1** (AAA)
- `prefers-reduced-motion: reduce` 시 모든 애니메이션(pulse, spinner) 정적 표시

---

## 주요 코드 변경 사항

### `checker.py` — Docker: Google Chrome 사용
```python
def _detect_browser_channel() -> str | None:
    # Linux: google-chrome 감지 → "chrome" 반환
    # 못 찾으면 None 반환 (내장 Chromium 폴백)

# BrowserSession.start():
channel = _detect_browser_channel()
launch_kwargs = {"headless": True}
if channel:
    launch_kwargs["channel"] = channel
if platform.system() == "Linux":
    launch_kwargs["args"] = ["--no-sandbox", "--disable-dev-shm-usage"]
self._browser = self._pw.chromium.launch(**launch_kwargs)
```

### `config.py` — Docker 볼륨만 지원 (최소 변경)
```python
import os

base_dir = os.environ.get("SETTINGS_DIR", os.path.dirname(os.path.abspath(__file__)))
SETTINGS_FILE = os.path.join(base_dir, "settings.json")

# load() / save() 시그니처 변경 없음
```

### `notifier.py`, `scheduler.py`, `facilities.py`
**변경 없음.**

---

## Docker 구성

### `Dockerfile`
```dockerfile
FROM mcr.microsoft.com/playwright/python:v1.58.0-jammy

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
- 동시 접속 충돌 방지 (한 번에 한 사람이 쓴다는 전제 — 여러 탭에서 start 호출 시 409 응답으로 충분)
- 다크모드 토글 (페이지는 light 고정, 로그 영역만 dark 카드)

---

## 검증
1. `docker compose up -d` 후 `http://localhost:8000` 접속
2. 첫 로드: 빈 상태 안내 표시 확인
3. 설정 입력 → [시작] → 버튼 spinner → 상태 "모니터링 중" + 보조 라인 표시 확인
4. [중지] → 상태 "중지", 버튼 START 로 토글 확인
5. 실행 중 `/api/start` 재호출 → 409 + 인라인 토스트 확인
6. [Slack 테스트] → 성공 토스트 + 웹훅 메시지 수신 확인
7. 페이지 새로고침 → 상태 + 로그 버퍼 + 보조 라인 복원 확인
8. WS 강제 끊김 → 인라인 배너 + 3초 후 자동 재연결 확인
9. 로그 위로 스크롤 → autoscroll pause + "↓ 새 로그" 버튼 확인
10. 키보드 Tab → focus ring + 의도된 순서 확인
11. 모바일 viewport (375px) → 세로 스택 + 로그 영역 240px 이상 확인
12. Oracle Cloud VM 동일 절차 반복

---

## 디자인 목업

`mockups/index.html` — 정적 HTML 목업. 실제 앱이 아니라 디자인 토큰/레이아웃/상태 표현 검증용. 브라우저로 열어 시각 확인.
