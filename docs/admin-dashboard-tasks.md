# Admin 현황판 구현 태스크

현재 멀티유저 구조에서 운영자가 누가 언제부터 사용 중인지 확인할 수 있는 읽기 전용 admin 페이지를 추가한다.
**순서대로 진행**할 것 (태스크 4는 태스크 1~3 완료 후 진행).

---

## 사전 정보

| 항목 | 값 |
|------|-----|
| 프로젝트 루트 | `YeonsuBot-Web/` |
| Admin 페이지 | `GET /admin` |
| Admin API | `GET /api/admin/sessions` |
| Admin 인증 | `ADMIN_PASSWORD` 환경변수 + `X-YeonsuBot-Admin-Password` 헤더 |
| 범위 | 읽기 전용 현황판 |
| 표시 정보 | 계정명, 세션 수, 최초 로그인, 마지막 활동, 실행 여부, 현재 상태, 마지막 체크, 연결 창 수 |
| 비표시 정보 | 비밀번호, 세션 토큰, 예약 대상 연수원/날짜, 로그 내용 |

---

## 태스크 1 — auth.py: Admin 인증 헬퍼 추가

**대상 파일:** `auth.py`
**선행 조건:** 없음

**현재 상태:**
- 일반 사용자 인증은 `current_user()` dependency가 담당
- 세션 토큰은 `X-YeonsuBot-Session` 헤더 우선, Cookie fallback
- admin 전용 인증 로직 없음

**구현 목표:**
- `ADMIN_PASSWORD` 환경변수를 읽는 admin 인증 dependency 추가
- 요청 헤더 `X-YeonsuBot-Admin-Password` 값과 `ADMIN_PASSWORD`를 비교
- `ADMIN_PASSWORD` 미설정 시 admin API 접근 차단
- 일반 사용자 세션 인증과 admin 인증을 분리

---

### 한글 프롬프트

```
YeonsuBot-Web/auth.py에 admin 전용 인증 dependency를 추가해줘.

현재 상태:
- 일반 사용자 인증은 current_user()가 담당
- admin 페이지/API용 인증은 아직 없음

구현할 내용:
1. 파일 상단에 os, secrets import가 필요한지 확인하고 추가
2. ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD") 방식으로 매 요청마다 환경변수를 읽거나, 헬퍼 내부에서 os.getenv("ADMIN_PASSWORD")를 호출
3. 아래 FastAPI dependency 추가:

   def current_admin(request: Request) -> bool:
       ...

4. current_admin 동작:
   - ADMIN_PASSWORD 환경변수가 비어 있으면 HTTPException(status_code=503, detail="admin 비밀번호가 설정되지 않았습니다.") 발생
   - 요청 헤더 X-YeonsuBot-Admin-Password 값을 읽음
   - 헤더가 없거나 ADMIN_PASSWORD와 다르면 HTTPException(status_code=401, detail="admin 인증이 필요합니다.") 발생
   - 비교는 secrets.compare_digest 사용
   - 성공 시 True 반환

주의:
- 기존 current_user(), create_session(), resolve_session(), destroy_session() 동작은 바꾸지 말 것
- 일반 사용자 세션 토큰으로 admin 접근을 허용하지 말 것
- admin 비밀번호 값을 로그에 남기지 말 것
```

---

## 태스크 2 — auth.py: 세션 스냅샷 조회 함수 추가

**대상 파일:** `auth.py`
**선행 조건:** 없음

**현재 상태:**
- 세션 저장소 `_sessions: dict[str, SessionInfo]`가 모듈 내부에 있음
- 외부에서 현재 세션 목록을 안전하게 읽는 공개 함수 없음
- 같은 사용자가 여러 창에서 로그인하면 session_id가 여러 개 생길 수 있음

**구현 목표:**
- admin API가 `_sessions`를 직접 만지지 않도록 스냅샷 함수 추가
- 만료 세션 정리 후 username 기준으로 집계
- 같은 username의 여러 세션은 한 항목으로 묶음

**응답 항목:**

| 필드 | 의미 |
|------|------|
| `username` | 계정명 |
| `session_count` | 해당 계정의 활성 세션 수 |
| `first_created_at` | 가장 이른 세션 생성 시각 |
| `last_seen_at` | 가장 최근 활동 시각 |

---

### 한글 프롬프트

```
YeonsuBot-Web/auth.py에 admin 현황판용 세션 스냅샷 함수를 추가해줘.

현재 상태:
- _sessions: dict[str, SessionInfo] 가 모듈 내부에 있음
- SessionInfo에는 username, created_at, last_seen_at 필드가 있음

구현할 함수:
    def admin_session_snapshot() -> list[dict]:
        ...

동작:
1. 먼저 _purge_expired()를 호출해서 만료 세션 제거
2. _sessions.values()를 username 기준으로 집계
3. 같은 username이 여러 세션을 가진 경우 한 항목으로 묶음
4. 각 항목은 아래 dict 형태:
   {
       "username": username,
       "session_count": 세션 수,
       "first_created_at": 가장 이른 created_at datetime,
       "last_seen_at": 가장 늦은 last_seen_at datetime,
   }
5. 반환 순서는 last_seen_at 내림차순

주의:
- datetime은 문자열로 변환하지 말고 timezone-aware datetime 객체 그대로 반환
- session_id/token 값은 절대 반환하지 말 것
- _sessions 자체를 반환하지 말 것
- 기존 인증 함수 동작은 바꾸지 말 것
```

---

## 태스크 3 — web_server.py: Admin API 추가

**대상 파일:** `web_server.py`
**선행 조건:** 태스크 1, 태스크 2 완료 후 진행

**현재 상태:**
- `registry.contexts()`로 사용자별 `SessionContext` 목록 조회 가능
- `SessionContext`에는 `username`, `scheduler`, `ws_clients`, `current_status`, `last_check_at`이 있음
- `auth.admin_session_snapshot()`와 `auth.current_admin()`은 태스크 1~2에서 추가됨

**구현 목표:**
- `GET /api/admin/sessions` 추가
- `Depends(auth.current_admin)`로 admin 인증 적용
- `auth.admin_session_snapshot()` 결과와 `registry.contexts()` 결과를 username 기준으로 병합
- 모든 시각은 KST 문자열로 변환

**응답 형식:**

```json
{
  "sessions": [
    {
      "username": "user1",
      "session_count": 2,
      "first_created_at": "2026-05-15 01:20:30",
      "last_seen_at": "2026-05-15 02:10:11",
      "has_context": true,
      "running": true,
      "status": "모니터링 중",
      "last_check_at": "02:09:50",
      "ws_client_count": 1
    }
  ]
}
```

---

### 한글 프롬프트

```
YeonsuBot-Web/web_server.py에 읽기 전용 admin 세션 현황 API를 추가해줘.

선행 조건:
- auth.current_admin dependency가 존재함
- auth.admin_session_snapshot() 함수가 존재함

추가할 엔드포인트:
    @app.get("/api/admin/sessions")
    async def api_admin_sessions(_: bool = Depends(auth.current_admin)) -> JSONResponse:
        ...

구현 내용:
1. auth.admin_session_snapshot()으로 계정별 세션 집계를 가져옴
2. registry.contexts()를 username 기준 dict로 만듦
3. 세션 집계와 context를 username 기준으로 병합
4. 각 항목에 아래 필드를 포함:
   - username
   - session_count
   - first_created_at
   - last_seen_at
   - has_context
   - running
   - status
   - last_check_at
   - ws_client_count
5. first_created_at, last_seen_at은 KST 기준 "YYYY-MM-DD HH:MM:SS" 문자열로 변환
6. context가 없는 계정은 running=False, status="중지", last_check_at=None, ws_client_count=0
7. 세션이 없지만 context만 있는 경우도 표시되도록 context-only 항목도 포함
8. 반환 JSON은 {"sessions": [...]} 형태

주의:
- 비밀번호, 세션 토큰, 예약 대상 연수원/날짜, 로그 내용은 반환하지 말 것
- 기존 /api/status, /api/start, /api/stop 동작은 바꾸지 말 것
- 시간 변환에는 기존 _KST를 사용
```

---

## 태스크 4 — templates/admin.html: Admin 현황판 UI 추가

**대상 파일:** `templates/admin.html` (신규)
**선행 조건:** 태스크 3 완료 후 진행

**현재 상태:**
- 사용자용 UI는 `templates/index.html`에 있음
- admin 페이지 HTML은 없음

**구현 목표:**
- Vanilla JS 기반 단일 HTML 페이지 추가
- admin 비밀번호 입력 화면 제공
- 인증 성공 후 읽기 전용 현황판 표시
- 새로고침 버튼 + 10초 자동 갱신
- Apple 시스템 기반 디자인 톤 유지

**표시 컬럼:**
- 계정
- 세션 수
- 최초 로그인
- 마지막 활동
- 실행 여부
- 현재 상태
- 마지막 체크
- 연결 창 수

---

### 한글 프롬프트

```
YeonsuBot-Web/templates/admin.html 파일을 새로 만들어 admin 현황판 UI를 구현해줘.

요구사항:
1. Vanilla HTML/CSS/JS만 사용
2. 외부 프레임워크 추가 금지
3. 처음 진입 시 admin 비밀번호 입력 화면 표시
4. 비밀번호 입력 후 /api/admin/sessions 호출
5. 요청 헤더에 X-YeonsuBot-Admin-Password를 포함
6. 인증 성공 시 현황판 표시
7. 현황판에는 아래 컬럼을 표로 표시:
   - 계정
   - 세션 수
   - 최초 로그인
   - 마지막 활동
   - 실행 여부
   - 현재 상태
   - 마지막 체크
   - 연결 창 수
8. 새로고침 버튼 제공
9. 인증 성공 후 10초마다 자동 갱신
10. 인증 실패 시 비밀번호 입력 화면에 오류 메시지 표시

디자인:
- 기존 Apple 시스템 톤과 맞춤 (#0071e3, #f5f5f7, #1d1d1f)
- shadow 없는 flat 디자인
- 모바일에서도 표가 깨지지 않도록 가로 스크롤 허용
- 운영 도구이므로 과한 히어로/카드 장식 없이 간결하게 구성

주의:
- 예약 대상 연수원/날짜, 로그 내용, 세션 토큰, 비밀번호는 화면에 표시하지 말 것
- 강제 중지/로그아웃 같은 조작 버튼은 만들지 말 것
- admin 비밀번호는 localStorage/sessionStorage에 저장하지 말고 메모리 변수로만 유지
```

---

## 태스크 5 — web_server.py: Admin HTML 라우트 추가

**대상 파일:** `web_server.py`
**선행 조건:** 태스크 4 완료 후 진행

**현재 상태:**
- `/` 라우트는 `templates/index.html`을 반환
- `/admin` 라우트 없음

**구현 목표:**
- `ADMIN_HTML = TEMPLATES_DIR / "admin.html"` 상수 추가
- `GET /admin` 라우트 추가
- `templates/admin.html` 파일이 없으면 500 HTML 응답

---

### 한글 프롬프트

```
YeonsuBot-Web/web_server.py에 admin 페이지 라우트를 추가해줘.

현재 상태:
- INDEX_HTML = TEMPLATES_DIR / "index.html" 상수가 있음
- GET / 라우트는 INDEX_HTML을 읽어서 반환함

추가할 내용:
1. INDEX_HTML 근처에 ADMIN_HTML = TEMPLATES_DIR / "admin.html" 추가
2. 아래 라우트 추가:

   @app.get("/admin", response_class=HTMLResponse)
   async def admin_page() -> HTMLResponse:
       ...

3. admin_page 동작:
   - ADMIN_HTML 파일이 없으면 "<h1>templates/admin.html 을 찾을 수 없습니다.</h1>"를 500으로 반환
   - 파일이 있으면 UTF-8로 읽어 HTMLResponse 반환

주의:
- /admin HTML 반환 자체에는 admin 인증을 걸지 말 것
- 실제 데이터 API인 /api/admin/sessions에서 auth.current_admin으로 보호함
- 기존 / 라우트는 건드리지 말 것
```

---

## 태스크 6 — .env.example: ADMIN_PASSWORD 추가

**대상 파일:** `.env.example`
**선행 조건:** 없음 (독립 태스크)

**현재 상태:**
- admin 비밀번호 환경변수 예시 없음

**구현 목표:**
- `.env.example` 하단에 admin 설정 섹션 추가
- `ADMIN_PASSWORD=` 예시 추가
- 비워두면 admin API 비활성화됨을 명시

---

### 한글 프롬프트

```
YeonsuBot-Web/.env.example 파일 하단에 admin 현황판 설정 섹션을 추가해줘.

추가할 내용:
# Admin 현황판 설정 (없으면 admin API 비활성화)
ADMIN_PASSWORD=

주의:
- 기존 내용은 수정하지 말 것
- 실제 비밀번호 값은 넣지 말 것
```

---

## 태스크 7 — 검증

**대상 파일:** 없음
**선행 조건:** 태스크 1~6 완료 후 진행

**검증 목표:**
- admin 인증
- admin API 응답 형식
- admin UI 표시
- 기존 사용자 기능 회귀

---

### 한글 프롬프트

```
YeonsuBot-Web admin 현황판 구현을 검증해줘.

검증 항목:
1. ADMIN_PASSWORD 미설정 상태에서 GET /api/admin/sessions가 차단되는지 확인
2. ADMIN_PASSWORD 설정 후 잘못된 X-YeonsuBot-Admin-Password로 요청하면 인증 실패하는지 확인
3. 올바른 X-YeonsuBot-Admin-Password로 요청하면 {"sessions": [...]} JSON이 반환되는지 확인
4. 응답에 비밀번호, 세션 토큰, 예약 대상 연수원/날짜, 로그 내용이 포함되지 않는지 확인
5. 같은 계정으로 여러 창 로그인 시 session_count가 증가하는지 확인
6. 봇 시작/중지 후 running/status/last_check_at/ws_client_count가 반영되는지 확인
7. /admin 페이지가 열리고 비밀번호 입력 후 표가 표시되는지 확인
8. 기존 /api/status, /api/settings, /api/start, /api/stop, /ws 동작이 깨지지 않았는지 확인

가능하면 uv run python main.py로 로컬 서버를 띄우고 curl 또는 브라우저로 확인해줘.
테스트 중 실제 예약이 실행되지 않도록 /api/start는 필요한 경우에만 조심해서 사용해줘.
```

---

## 진행 순서 요약

```
태스크 6  ← 독립, 언제든 가능
태스크 1  ← auth.py admin 인증
태스크 2  ← auth.py 세션 스냅샷
    ↓
태스크 3  ← web_server.py admin API
    ↓
태스크 4  ← templates/admin.html
    ↓
태스크 5  ← web_server.py admin HTML 라우트
    ↓
태스크 7  ← 검증
```
