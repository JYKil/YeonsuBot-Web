"""연수원 예약 가능 확인 + 자동 예약 (Playwright 기반)."""

from __future__ import annotations

import logging
import os
import platform
import random
from datetime import datetime, timedelta

from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout

from facilities import get_facility_name

logger = logging.getLogger(__name__)


def _random_delay(page, base_ms: int = 2000, jitter_ms: int = 1000):
    """사람처럼 보이도록 랜덤 대기."""
    delay = base_ms + random.randint(0, jitter_ms)
    page.wait_for_timeout(delay)

BASE_URL = "https://yeonsu.eseoul.go.kr"
LOGIN_URL = f"{BASE_URL}/loginProcAjax"
ONLINE_RSV_URL = f"{BASE_URL}/onlineRsv/list"

# 브라우저 재시작 주기 (메모리 누수 방지)
MAX_CHECKS_BEFORE_RESTART = 50


class LoginError(Exception):
    """로그인 실패 (아이디/비밀번호 오류)."""


class BrowserNotFoundError(Exception):
    """시스템에 Chrome 또는 Edge 브라우저를 찾을 수 없음."""


class BookingError(Exception):
    """예약 플로우 중 오류 발생."""


def _detect_browser_channel() -> str | None:
    """시스템에 설치된 Chrome 또는 Edge를 탐색하여 Playwright channel 이름을 반환한다.

    못 찾으면 None 반환 (Playwright 내장 Chromium으로 폴백).
    Linux/Docker 환경에서는 내장 Chromium이 기본이며, 이 함수는 항상 None.
    """
    system = platform.system()

    if system == "Darwin":
        candidates = [
            ("/Applications/Google Chrome.app", "chrome"),
            ("/Applications/Microsoft Edge.app", "msedge"),
        ]
        for path, channel in candidates:
            if os.path.exists(path):
                logger.info("시스템 브라우저 사용: %s", channel)
                return channel

    elif system == "Windows":
        dirs = [
            os.environ.get("PROGRAMFILES", r"C:\Program Files"),
            os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)"),
            os.environ.get("LOCALAPPDATA", ""),
        ]
        candidates = [
            (r"Google\Chrome\Application\chrome.exe", "chrome"),
            (r"Microsoft\Edge\Application\msedge.exe", "msedge"),
        ]
        for base in dirs:
            if not base:
                continue
            for rel, channel in candidates:
                if os.path.isfile(os.path.join(base, rel)):
                    logger.info("시스템 브라우저 사용: %s", channel)
                    return channel

    else:  # Linux
        import shutil
        candidates = [
            ("google-chrome", "chrome"),
            ("microsoft-edge", "msedge"),
        ]
        for exe, channel in candidates:
            if shutil.which(exe):
                logger.info("시스템 브라우저 사용: %s", channel)
                return channel

    logger.debug("시스템 브라우저 미발견, Playwright 내장 Chromium으로 폴백")
    return None


# JS: 달력에서 예약 가능 날짜 읽기
_JS_READ_CALENDAR = """
(targetDates) => {
    const targetSet = new Set(targetDates);
    const blocked = [];
    const available = [];
    document.querySelectorAll('td.targetDate[data-date]').forEach(td => {
        const rawDate = td.getAttribute('data-date') || '';
        const date = rawDate.replace(/\\./g, '');
        if (!targetSet.has(date)) return;
        const btn = td.querySelector('button');
        if (!btn || btn.disabled || btn.classList.contains('day-prev')) {
            blocked.push(date);
        } else {
            available.push(date);
        }
    });
    return {blocked, available};
}
"""


class BrowserSession:
    """Playwright 브라우저 세션을 관리한다.

    세션(쿠키)을 유지하면서 매 확인마다 페이지만 새로 로드한다.
    빈방 발견 시 같은 세션에서 바로 예약을 진행할 수 있다.

    상태 흐름:
      start() → check() → [빈방 발견] → book() → stop()
                  ↑                         ↓
                  └── [실패] ← ─── ─── ─── ┘
    """

    def __init__(self):
        self._pw = None
        self._browser = None
        self._context = None
        self._check_count = 0
        self._username = ""
        self._password = ""

    @property
    def is_alive(self) -> bool:
        return self._browser is not None and self._context is not None

    def start(self, username: str, password: str):
        """브라우저를 시작하고 로그인한다."""
        self._username = username
        self._password = password
        self._check_count = 0

        self._pw = sync_playwright().start()
        channel = _detect_browser_channel()
        launch_kwargs: dict = {"headless": True}
        if channel:
            launch_kwargs["channel"] = channel
        if platform.system() == "Linux":
            # Docker/Linux — root 실행 시 샌드박스 해제 필요
            launch_kwargs["args"] = ["--no-sandbox", "--disable-dev-shm-usage"]
        self._browser = self._pw.chromium.launch(**launch_kwargs)
        self._context = self._browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        )
        # navigator.webdriver 플래그 제거 (자동화 탐지 우회)
        self._context.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")

        self._do_login()
        logger.info("브라우저 세션 시작 완료")

    def _do_login(self):
        """로그인 수행. 세션 쿠키가 context에 설정된다."""
        logger.info("로그인 중...")
        page = self._context.new_page()
        try:
            # goto 타임아웃 시 1회 재시도 (공공 사이트 응답 지연 대응)
            try:
                page.goto(BASE_URL, wait_until="domcontentloaded", timeout=30000)
            except PlaywrightTimeout:
                logger.warning("로그인 페이지 로드 타임아웃, 5초 후 재시도...")
                page.close()
                import time as _time
                _time.sleep(5)
                page = self._context.new_page()
                page.goto(BASE_URL, wait_until="domcontentloaded", timeout=30000)
            resp = page.request.post(
                LOGIN_URL,
                form={"mbmr_id": self._username, "mbmr_pwd": self._password},
                headers={"X-Requested-With": "XMLHttpRequest"},
            )
            if resp.status != 200:
                raise LoginError(f"로그인 실패 (status={resp.status})")
            try:
                data = resp.json()
            except Exception:
                raise LoginError("로그인 응답을 파싱할 수 없습니다.")
            result = data.get("result", "")
            if result in ("fail", "notMatch") or data.get("resultCode") == "01":
                raise LoginError("아이디 또는 비밀번호가 올바르지 않습니다.")
            if result not in ("success", "pwdNextChange"):
                raise LoginError(f"로그인 실패: 예상치 못한 응답 ({result!r})")
            logger.info("로그인 성공, 대기 중...")
            _random_delay(page, 3000, 1500)
        finally:
            page.close()

    def _need_restart(self) -> bool:
        """브라우저 재시작이 필요한지 확인한다."""
        return self._check_count >= MAX_CHECKS_BEFORE_RESTART

    def _restart(self):
        """브라우저를 재시작한다 (메모리 누수 방지)."""
        logger.info("브라우저 재시작 (%d회 확인 후)", self._check_count)
        self.stop()
        self.start(self._username, self._password)

    def check(self, yeonsu_gbn: str, target_dates: list[str]) -> list[str] | None:
        """예약 가능 날짜를 확인한다.

        Returns:
            예약 가능 날짜 목록. 오류 시 None.
        """
        if not self.is_alive:
            return None

        # 브라우저 재시작 체크
        if self._need_restart():
            self._restart()

        self._check_count += 1
        page = None
        try:
            page = self._context.new_page()
            url = f"{ONLINE_RSV_URL}?ser_yeonsu_gbn={yeonsu_gbn}"

            # goto 타임아웃 시 1회 재시도 (연속 요청 시 사이트 응답 지연 대응)
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=30000)
            except PlaywrightTimeout:
                logger.warning("페이지 로드 타임아웃, 5초 후 재시도...")
                page.close()
                page = None
                import time as _time
                _time.sleep(5)
                page = self._context.new_page()
                page.goto(url, wait_until="domcontentloaded", timeout=30000)

            # 세션 만료 확인 → 재로그인
            if "login" in page.url.lower():
                logger.warning("세션 만료 감지, 재로그인...")
                page.close()
                page = None
                self._do_login()
                page = self._context.new_page()
                page.goto(url, wait_until="domcontentloaded", timeout=30000)
                if "login" in page.url.lower():
                    logger.error("재로그인 후에도 세션 만료")
                    return None

            # 연수원 선택 — URL 파라미터(?ser_yeonsu_gbn=)로 이미 선택됨
            # <select> 값만 동기화, roomViewSend() 호출 불필요
            facility_name = get_facility_name(yeonsu_gbn)
            page.evaluate(
                """(code) => {
                    const sel = document.getElementById('ser_yeonsu_gbn');
                    if (sel) sel.value = code;
                }""",
                yeonsu_gbn,
            )
            logger.info("연수원 '%s' 선택 (코드: %s)", facility_name, yeonsu_gbn)
            _random_delay(page, 1000, 500)

            # 달력 읽기
            logger.info("달력 검색 중...")

            if page.evaluate("typeof showCalendar === 'function'"):
                page.evaluate("showCalendar()")
            else:
                logger.info("showCalendar 함수 없음, 달력이 이미 로드되었는지 확인")

            # 달력 요소가 DOM에 나타날 때까지 대기 (숨김 상태여도 OK)
            try:
                page.wait_for_selector('td.targetDate[data-date]', state='attached', timeout=10000)
            except PlaywrightTimeout:
                logger.warning("달력 요소 대기 타임아웃, 대체 셀렉터 시도")
                try:
                    page.wait_for_selector('td[data-date]', state='attached', timeout=5000)
                except PlaywrightTimeout:
                    logger.warning("달력 요소를 찾을 수 없음")
            _random_delay(page, 1000, 500)

            # 달력 읽기 (빈 결과 시 최대 2회 재시도)
            result = None
            for attempt in range(3):
                result = page.evaluate(_JS_READ_CALENDAR, target_dates)
                if result.get("blocked") or result.get("available"):
                    break
                if attempt < 2:
                    logger.info("달력 요소 없음, 2초 후 재시도... (%d/3)", attempt + 1)
                    page.wait_for_timeout(2000)

            blocked = result.get("blocked", [])
            available_set = set(result.get("available", []))

            logger.info("달력 결과: 불가 %s, 가능 %s", sorted(blocked), sorted(available_set))

            available_dates = sorted(day for day in target_dates if day in available_set)
            missing_dates = [day for day in target_dates if day not in available_set]

            if available_dates:
                logger.info("예약 가능: %s / 불가: %s", available_dates, missing_dates)

            return available_dates

        except LoginError:
            raise
        except PlaywrightTimeout as exc:
            logger.warning("브라우저 확인 실패 (타임아웃): %s", exc)
            return None
        except Exception as exc:
            logger.warning("브라우저 확인 실패: %s", exc)
            return None
        finally:
            if page:
                try:
                    page.close()
                except Exception:
                    pass

    def book(self, yeonsu_gbn: str, target_dates: list[str],
             stop_event=None) -> bool:
        """지정된 날짜 범위의 객실을 예약한다.

        Args:
            yeonsu_gbn: 연수원 코드
            target_dates: 예약할 날짜 목록 (YYYYMMDD). 첫 번째=체크인, 마지막+1일=체크아웃
            stop_event: 중지 신호 (threading.Event). 설정 시 예약 중단.

        Returns:
            예약 성공 여부
        """
        if not self.is_alive:
            raise BookingError("브라우저 세션이 활성화되지 않음")

        def _stopped():
            return stop_event is not None and stop_event.is_set()

        checkin_date = target_dates[0]
        # 체크아웃 = 마지막 날짜 + 1일
        last_dt = datetime.strptime(target_dates[-1], "%Y%m%d")
        checkout_date = (last_dt + timedelta(days=1)).strftime("%Y%m%d")

        page = None
        try:
            page = self._context.new_page()
            url = f"{ONLINE_RSV_URL}?ser_yeonsu_gbn={yeonsu_gbn}"
            page.goto(url, wait_until="domcontentloaded", timeout=30000)

            # RESAGREE 쿠키 설정 (예약안내 팝업 건너뛰기, 1차 방어)
            self._context.add_cookies([{
                "name": "RESAGREE",
                "value": "Y",
                "domain": "yeonsu.eseoul.go.kr",
                "path": "/",
            }])

            # 세션 만료 확인
            if "login" in page.url.lower():
                logger.warning("예약 시도 중 세션 만료, 재로그인...")
                page.close()
                page = None
                self._do_login()
                page = self._context.new_page()
                page.goto(url, wait_until="domcontentloaded", timeout=30000)
                # 재로그인 후에도 쿠키 재설정
                self._context.add_cookies([{
                    "name": "RESAGREE",
                    "value": "Y",
                    "domain": "yeonsu.eseoul.go.kr",
                    "path": "/",
                }])

            # dialog 핸들러 등록 (자동 체크아웃 alert 등 대응)
            dialog_results = []

            def handle_dialog(dialog):
                # 크롬 브라우저 경고는 무시 (Chromium 환경에서 반복 발생)
                if "크롬 브라우저" in dialog.message:
                    dialog.accept()
                    return
                # 브라우저 감지에서 오는 단독 "실패" alert 무시
                if dialog.message.strip() == "실패":
                    dialog.accept()
                    return
                logger.info("[예약] dialog: type=%s, message=%s", dialog.type, dialog.message)
                dialog_results.append({"type": dialog.type, "message": dialog.message})
                dialog.accept()

            page.on("dialog", handle_dialog)

            # 1단계: 연수원 선택 — URL 파라미터(?ser_yeonsu_gbn=)로 이미 선택됨
            # <select> 값만 동기화, roomViewSend() 호출 불필요
            facility_name = get_facility_name(yeonsu_gbn)
            page.evaluate(
                """(code) => {
                    const sel = document.getElementById('ser_yeonsu_gbn');
                    if (sel) sel.value = code;
                }""",
                yeonsu_gbn,
            )
            logger.info("[예약] 연수원 '%s' 선택 (코드: %s)", facility_name, yeonsu_gbn)
            _random_delay(page, 1000, 500)

            if _stopped():
                raise BookingError("중지 요청됨")

            # 2단계: 달력 표시 후 체크인 날짜 클릭
            page.evaluate("showCalendar()")
            try:
                page.wait_for_selector('td.targetDate[data-date]', state='attached', timeout=10000)
            except PlaywrightTimeout:
                logger.warning("[예약] 달력 요소 대기 타임아웃")
            _random_delay(page, 1000, 500)

            # JS evaluate로 날짜 선택 (onclick 직접 호출 — visible 불필요)
            checkin_fmt = f"{checkin_date[:4]}.{checkin_date[4:6]}.{checkin_date[6:]}"
            try:
                page.wait_for_selector(
                    f'td.targetDate[data-date="{checkin_fmt}"]', state='attached', timeout=5000)
                page.evaluate("""(fmt) => {
                    const td = document.querySelector(`td.targetDate[data-date="${fmt}"]`);
                    if (td && td.onclick) td.onclick();
                    else if (td) td.querySelector('button')?.click();
                }""", checkin_fmt)
            except PlaywrightTimeout:
                raise BookingError(f"체크인 날짜 {checkin_date} 버튼을 찾을 수 없음")
            logger.info("[예약] 체크인 날짜 %s 클릭 완료", checkin_date)
            _random_delay(page, 2000, 1000)

            # 체크아웃 날짜 (1박이든 다박이든 항상 명시적 클릭)
            checkout_fmt = f"{checkout_date[:4]}.{checkout_date[4:6]}.{checkout_date[6:]}"
            try:
                page.wait_for_selector(
                    f'td.targetDate[data-date="{checkout_fmt}"]', state='attached', timeout=5000)
                page.evaluate("""(fmt) => {
                    const td = document.querySelector(`td.targetDate[data-date="${fmt}"]`);
                    if (td && td.onclick) td.onclick();
                    else if (td) td.querySelector('button')?.click();
                }""", checkout_fmt)
                logger.info("[예약] 체크아웃 날짜 %s 클릭 완료", checkout_date)
            except PlaywrightTimeout:
                # 다음날 예약 불가 시 사이트가 자동 설정 ("자동설정" alert)
                auto_set = any("자동설정" in dr.get("message", "") for dr in dialog_results)
                if auto_set:
                    logger.info("[예약] 체크아웃 사이트 자동 설정됨, 클릭 생략")
                else:
                    raise BookingError(f"체크아웃 날짜 {checkout_date} 버튼을 찾을 수 없음")
            _random_delay(page, 2000, 1000)

            if _stopped():
                raise BookingError("중지 요청됨")

            # 날짜 폼 필드 직접 설정 (rsvList()가 hidden 필드를 못 채울 수 있음)
            page.evaluate("""([ci, co]) => {
                ['check_in_day', 'check_in_day_hidden'].forEach(id => {
                    const el = document.getElementById(id);
                    if (el) el.value = ci;
                });
                ['check_out_day', 'check_out_day_hidden'].forEach(id => {
                    const el = document.getElementById(id);
                    if (el) el.value = co;
                });
            }""", [checkin_date, checkout_date])
            actual = page.evaluate("""() => ({
                ci: document.getElementById('check_in_day')?.value || '',
                co: document.getElementById('check_out_day')?.value || ''
            })""")
            logger.info("[예약] 날짜 필드 동기화: 체크인=%s, 체크아웃=%s",
                        actual['ci'], actual['co'])

            # 3단계: "선택일로 예약하기" 클릭
            logger.info("[예약] 선택일로 예약하기 클릭...")
            try:
                with page.expect_navigation(timeout=15000):
                    page.evaluate("search()")
            except PlaywrightTimeout:
                # navigation 없이 AJAX로 처리될 수도 있음
                logger.info("[예약] search() 후 페이지 이동 없음, AJAX 응답 대기")
            try:
                page.wait_for_load_state('networkidle', timeout=10000)
            except PlaywrightTimeout:
                logger.warning("[예약] search() 후 네트워크 안정 대기 타임아웃")
            logger.info("[예약] search() 후 현재 URL: %s", page.url)
            _random_delay(page, 1000, 500)

            # 4단계: 기관배정 팝업 닫기 (#notiNoRsvA → noRsvClose())
            try:
                page.wait_for_selector('#notiNoRsvA', state='visible', timeout=3000)
                # noRsvClose()가 정의되지 않을 수 있으므로 안전하게 호출
                page.evaluate("""() => {
                    if (typeof noRsvClose === 'function') {
                        noRsvClose();
                    } else {
                        // 함수 미정의 시 직접 팝업 숨김
                        const el = document.getElementById('notiNoRsvA');
                        if (el) el.style.display = 'none';
                        document.querySelectorAll('.ui-widget-overlay, .ui-dialog')
                            .forEach(e => e.style.display = 'none');
                    }
                }""")
                logger.info("[예약] 기관배정 팝업 닫기 호출")
                # 팝업 오버레이가 실제로 사라질 때까지 대기
                try:
                    page.wait_for_selector('#notiNoRsvA', state='hidden', timeout=5000)
                except PlaywrightTimeout:
                    # 강제로 오버레이 숨김
                    page.evaluate("""() => {
                        document.querySelectorAll('.ui-widget-overlay, .ui-dialog')
                            .forEach(el => el.style.display = 'none');
                    }""")
                    logger.warning("[예약] 팝업 강제 숨김 처리")
                logger.info("[예약] 기관배정 팝업 닫기 완료")
                _random_delay(page, 1000, 500)
            except PlaywrightTimeout:
                logger.info("[예약] 기관배정 팝업 없음, 건너뜀")

            if _stopped():
                raise BookingError("중지 요청됨")

            # 5단계: 첫 번째 가용 객실의 "객실선택하기" 클릭
            try:
                page.wait_for_selector('#room_contents', state='attached', timeout=10000)
                page.wait_for_function(
                    "document.querySelector('input[name=\"termType\"]') !== null", timeout=10000)
                page.evaluate("""() => {
                    const radio = document.querySelector('input[name="termType"]');
                    if (radio) {
                        radio.checked = true;
                        radio.click();
                        radio.dispatchEvent(new Event('change', {bubbles: true}));
                    }
                }""")
            except PlaywrightTimeout:
                try:
                    body_text = page.inner_text('body')[:500]
                    logger.warning("[예약] 객실 페이지 내용: %s", body_text)
                except Exception:
                    pass
                raise BookingError("'객실선택하기' 버튼을 찾을 수 없음")
            logger.info("[예약] 객실선택하기 클릭 완료")

            # 객실 선택 후 예약 상세 폼 활성화 확인
            try:
                page.wait_for_selector('#form_rsv1', state='visible', timeout=10000)
                logger.info("[예약] 예약 상세 폼 로드 확인")
            except PlaywrightTimeout:
                raise BookingError("객실 선택 후 예약 폼이 표시되지 않음")
            _random_delay(page, 2000, 1000)

            if _stopped():
                raise BookingError("중지 요청됨")

            # 6단계: "예약하기" 클릭 (onclick="online_guide_popup()")
            logger.info("[예약] 객실 선택 완료, 예약 제출 중...")

            # online_guide_popup() 호출 — 팝업 창 또는 바로 폼 제출
            # dialog 핸들러가 브라우저 confirm/alert 자동 수락
            pre_click_url = page.url
            popup_page = None
            navigated = False

            # 팝업 창 감지 핸들러 등록
            def _on_popup(p):
                nonlocal popup_page
                popup_page = p

            self._context.on("page", _on_popup)

            try:
                page.evaluate("online_guide_popup()")
            except Exception as exc:
                logger.warning("[예약] online_guide_popup() 오류: %s", exc)

            # 팝업 또는 네비게이션 감지 대기 (짧게)
            page.wait_for_timeout(3000)
            self._context.remove_listener("page", _on_popup)

            if popup_page:
                # 예약안내 팝업 창 처리
                logger.info("[예약] 예약안내 팝업 창 감지: %s", popup_page.url)
                try:
                    popup_page.wait_for_load_state('domcontentloaded', timeout=10000)
                    popup_page.on("dialog", handle_dialog)

                    # 일괄동의 체크박스 클릭
                    agree_all = popup_page.locator(
                        "input[type='checkbox']#allAgree, "
                        "label:has-text('일괄동의'), "
                        "label:has-text('전체동의')"
                    )
                    if agree_all.count() > 0:
                        agree_all.first.click()
                        logger.info("[예약] 일괄동의 클릭")
                        _random_delay(popup_page, 500, 300)
                    else:
                        checkboxes = popup_page.locator("input[type='checkbox']")
                        for i in range(checkboxes.count()):
                            if not checkboxes.nth(i).is_checked():
                                checkboxes.nth(i).click()
                                _random_delay(popup_page, 200, 100)
                        logger.info("[예약] 개별 동의 %d개 클릭", checkboxes.count())

                    confirm_btn = popup_page.locator(
                        "button:has-text('예약하기'), "
                        "button:has-text('확인'), "
                        "button:has-text('동의'), "
                        "a:has-text('확인')"
                    )
                    if confirm_btn.count() > 0:
                        confirm_btn.first.click()
                        logger.info("[예약] 예약안내 확인 클릭")
                        _random_delay(popup_page, 2000, 1000)

                    try:
                        popup_page.wait_for_event('close', timeout=10000)
                    except PlaywrightTimeout:
                        pass
                except Exception as exc:
                    logger.warning("[예약] 예약안내 팝업 처리 중 오류: %s", exc)
                finally:
                    if not popup_page.is_closed():
                        popup_page.close()

                # 팝업 닫힌 후 메인 페이지 결과 대기
                _random_delay(page, 2000, 1000)
            else:
                # 팝업 없음 — RESAGREE 쿠키로 바로 폼 제출됨
                # 네비게이션 또는 네트워크 완료 대기
                logger.info("[예약] 팝업 없음, 폼 제출 결과 대기...")
                try:
                    page.wait_for_load_state('networkidle', timeout=10000)
                except PlaywrightTimeout:
                    pass
                _random_delay(page, 1000, 500)

            navigated = page.url != pre_click_url

            # 7단계: 결과 판단
            current_url = page.url

            try:
                page_text = page.inner_text("body")[:500]
            except Exception:
                page_text = ""

            # 페이지 텍스트에서 실패 키워드 확인
            # "불가" 제외: 성공 페이지에도 "취소 불가" 등 정책 안내에 포함됨
            fail_keywords_page = ["예약 실패", "예약실패", "마감", "오류", "에러"]
            for kw in fail_keywords_page:
                if kw in page_text:
                    raise BookingError(f"예약 실패 (페이지 응답): {kw}")

            if navigated:
                logger.info("[예약] 페이지 이동 감지: %s", current_url)
                return True

            # dialog 기반 판단 — 성공 메시지 우선 확인
            for dr in dialog_results:
                msg = dr.get("message", "")
                if "완료" in msg:
                    logger.info("[예약] 성공 dialog 감지: %s", msg)
                    return True

            fail_keywords = ["실패", "불가", "마감", "초과", "오류", "에러",
                             "없습니다", "선택해", "입력해", "확인해"]
            for dr in dialog_results:
                msg = dr.get("message", "")
                for kw in fail_keywords:
                    if kw in msg:
                        raise BookingError(f"예약 실패 (서버 응답): {msg}")

            # 네비게이션도 없고 실패 dialog도 없으면 → 성공 여부 불확실
            if not navigated:
                raise BookingError("예약 성공 여부 불확실 (페이지 이동 없음)")

        except BookingError:
            raise
        except PlaywrightTimeout as exc:
            raise BookingError(f"예약 중 타임아웃: {exc}")
        except Exception as exc:
            raise BookingError(f"예약 중 오류: {exc}")
        finally:
            if page:
                try:
                    page.close()
                except Exception:
                    pass

    def stop(self):
        """브라우저와 Playwright를 정리한다."""
        for obj in (self._context, self._browser):
            try:
                if obj:
                    obj.close()
            except Exception:
                pass
        try:
            if self._pw:
                self._pw.stop()
        except Exception:
            pass
        self._context = None
        self._browser = None
        self._pw = None
        self._check_count = 0


def date_range(start: str, end: str) -> list[str]:
    """YYYY-MM-DD 형식의 시작/종료일로부터 YYYYMMDD 날짜 목록을 생성한다."""
    try:
        start_dt = datetime.strptime(start, "%Y-%m-%d")
        end_dt = datetime.strptime(end, "%Y-%m-%d")
    except ValueError:
        return []

    dates = []
    current = start_dt
    while current <= end_dt:
        dates.append(current.strftime("%Y%m%d"))
        current += timedelta(days=1)
    return dates
