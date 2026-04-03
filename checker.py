"""연수원 예약 가능 확인 + 자동 예약 (Playwright 기반)."""

from __future__ import annotations

import logging
import os
import platform
from datetime import datetime, timedelta

from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout

from facilities import get_facility_name

logger = logging.getLogger(__name__)

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


def _detect_browser_channel() -> str:
    """시스템에 설치된 Chrome 또는 Edge를 탐색하여 Playwright channel 이름을 반환한다."""
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

    raise BrowserNotFoundError(
        "Chrome 또는 Edge 브라우저를 찾을 수 없습니다.\n"
        "Google Chrome 또는 Microsoft Edge를 설치한 후 다시 시도해 주세요."
    )


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
        self._browser = self._pw.chromium.launch(headless=True, channel=channel)
        self._context = self._browser.new_context()

        self._do_login()
        logger.info("브라우저 세션 시작 완료")

    def _do_login(self):
        """로그인 수행. 세션 쿠키가 context에 설정된다."""
        logger.info("로그인 중...")
        page = self._context.new_page()
        try:
            page.goto(BASE_URL, wait_until="domcontentloaded", timeout=15000)
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
            logger.info("로그인 성공, 3초 대기...")
            page.wait_for_timeout(3000)
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

            # 연수원 선택
            facility_name = get_facility_name(yeonsu_gbn)
            actual_code = page.evaluate(
                """(name) => {
                    const sel = document.getElementById('ser_yeonsu_gbn');
                    if (!sel) return null;
                    for (const opt of sel.options) {
                        if (opt.textContent.trim() === name) return opt.value;
                    }
                    return null;
                }""",
                facility_name,
            )
            if not actual_code:
                logger.warning("연수원 '%s' 옵션을 찾지 못함", facility_name)
                return None

            logger.info("연수원 '%s' 선택 (코드: %s)", facility_name, actual_code)
            page.evaluate(
                """(code) => {
                    const sel = document.getElementById('ser_yeonsu_gbn');
                    sel.value = code;
                    roomViewSend();
                }""",
                actual_code,
            )
            page.wait_for_timeout(3000)

            # 달력 읽기
            logger.info("달력 검색 중...")
            page.evaluate("showCalendar()")
            page.wait_for_timeout(3000)

            result = page.evaluate(_JS_READ_CALENDAR, target_dates)
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

    def book(self, yeonsu_gbn: str, target_date: str) -> bool:
        """지정된 날짜의 객실을 예약한다.

        Args:
            yeonsu_gbn: 연수원 코드
            target_date: 예약할 날짜 (YYYYMMDD)

        Returns:
            예약 성공 여부
        """
        if not self.is_alive:
            raise BookingError("브라우저 세션이 활성화되지 않음")

        page = None
        try:
            page = self._context.new_page()
            url = f"{ONLINE_RSV_URL}?ser_yeonsu_gbn={yeonsu_gbn}"
            page.goto(url, wait_until="domcontentloaded", timeout=30000)

            # 세션 만료 확인
            if "login" in page.url.lower():
                logger.warning("예약 시도 중 세션 만료, 재로그인...")
                page.close()
                page = None
                self._do_login()
                page = self._context.new_page()
                page.goto(url, wait_until="domcontentloaded", timeout=30000)

            # 1단계: 연수원 선택
            facility_name = get_facility_name(yeonsu_gbn)
            logger.info("[예약] 연수원 '%s' 선택", facility_name)
            actual_code = page.evaluate(
                """(name) => {
                    const sel = document.getElementById('ser_yeonsu_gbn');
                    if (!sel) return null;
                    for (const opt of sel.options) {
                        if (opt.textContent.trim() === name) return opt.value;
                    }
                    return null;
                }""",
                facility_name,
            )
            if not actual_code:
                raise BookingError(f"연수원 '{facility_name}' 옵션을 찾지 못함")

            page.evaluate(
                """(code) => {
                    const sel = document.getElementById('ser_yeonsu_gbn');
                    sel.value = code;
                    roomViewSend();
                }""",
                actual_code,
            )
            page.wait_for_timeout(3000)

            # 2단계: 달력 표시 후 날짜 클릭
            page.evaluate("showCalendar()")
            page.wait_for_timeout(3000)
            formatted = f"{target_date[:4]}.{target_date[4:6]}.{target_date[6:]}"
            logger.info("[예약] 날짜 클릭: %s", target_date)
            date_btn = page.locator(f'td.targetDate[data-date="{formatted}"] button')
            if date_btn.count() == 0:
                raise BookingError(f"날짜 {target_date} 버튼을 찾을 수 없음")
            date_btn.first.click()
            page.wait_for_timeout(2000)

            # 3단계: "선택일로 예약하기" 버튼 클릭 (button.btn_check → search() 호출)
            logger.info("[예약] '선택일로 예약하기' 클릭")
            reserve_btn = page.locator("button.btn_check")
            if reserve_btn.count() == 0:
                raise BookingError("'선택일로 예약하기' 버튼을 찾을 수 없음")
            reserve_btn.first.click()
            page.wait_for_timeout(2000)

            # 4단계: 기관배정 팝업 모달 닫기 (표시되는 경우에만)
            try:
                close_btn = page.locator(".modal.show button.close, .modal.show .btn-close, .modal.show button:has-text('닫기')")
                close_btn.first.click(timeout=3000)
                logger.info("[예약] 기관배정 팝업 닫기")
                page.wait_for_timeout(1000)
            except PlaywrightTimeout:
                logger.info("[예약] 기관배정 팝업 없음, 건너뜀")

            # 5단계: 첫 번째 가용 객실 선택
            logger.info("[예약] 객실 선택")
            room_btn = page.locator("button:has-text('객실선택'), a:has-text('객실선택'), button:has-text('선택')")
            if room_btn.count() == 0:
                raise BookingError("객실 선택 버튼을 찾을 수 없음")
            room_btn.first.click()
            page.wait_for_timeout(1000)

            # 6단계: dialog 핸들러 사전 등록 + "예약하기" 클릭
            dialog_results = []

            def handle_dialog(dialog):
                logger.info("[예약] dialog 발생: type=%s, message=%s", dialog.type, dialog.message)
                dialog_results.append({"type": dialog.type, "message": dialog.message})
                dialog.accept()

            page.on("dialog", handle_dialog)

            logger.info("[예약] '예약하기' 클릭")
            book_btn = page.locator("button:has-text('예약하기'), a:has-text('예약하기')")
            if book_btn.count() == 0:
                raise BookingError("'예약하기' 버튼을 찾을 수 없음")
            book_btn.first.click()
            page.wait_for_timeout(3000)

            # 7단계: confirm + alert 처리 (dialog 핸들러가 자동으로 accept)
            # dialog_results에 confirm, alert 순서로 쌓임

            # 8단계: dialog 결과 검증 + 분기 처리
            page.wait_for_timeout(2000)

            # dialog 메시지에서 실패 키워드 확인
            fail_keywords = ["실패", "불가", "마감", "초과", "오류", "에러", "없습니다"]
            for dr in dialog_results:
                msg = dr.get("message", "")
                for kw in fail_keywords:
                    if kw in msg:
                        raise BookingError(f"예약 실패 (서버 응답): {msg}")

            # 예약안내 페이지 감지 (첫 예약 시)
            current_url = page.url.lower()

            if "agree" in current_url or "약관" in page.content()[:500]:
                # 첫 예약: 예약안내 페이지
                logger.info("[예약] 예약안내 페이지 감지, 일괄동의 진행")
                try:
                    # 일괄동의 체크박스 클릭
                    agree_all = page.locator("input[type='checkbox']#allAgree, input[type='checkbox']:has-text('일괄'), label:has-text('일괄동의'), label:has-text('전체동의')")
                    if agree_all.count() > 0:
                        agree_all.first.click()
                        page.wait_for_timeout(500)
                    else:
                        # 개별 체크박스 모두 클릭
                        checkboxes = page.locator("input[type='checkbox']")
                        for i in range(checkboxes.count()):
                            if not checkboxes.nth(i).is_checked():
                                checkboxes.nth(i).click()
                                page.wait_for_timeout(200)

                    # 확인 버튼 클릭
                    confirm_btn = page.locator("button:has-text('확인'), button:has-text('동의'), a:has-text('확인')")
                    if confirm_btn.count() > 0:
                        confirm_btn.first.click()
                        page.wait_for_timeout(2000)
                    logger.info("[예약] 일괄동의 완료")
                except Exception as exc:
                    logger.warning("[예약] 일괄동의 처리 중 오류: %s", exc)

            # dialog가 하나도 안 왔으면 의심스러움
            if not dialog_results:
                logger.warning("[예약] dialog 응답 없음, 예약 성공 여부 불확실")

            logger.info("[예약] 예약 완료!")
            return True

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
