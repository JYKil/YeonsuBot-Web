"""Playwright 전용 워커 스레드 + 주기적 모니터링 스케줄러."""

import logging
import queue
import threading
import time
from enum import Enum, auto

from checker import BrowserSession, BookingError, LoginError, BrowserNotFoundError

logger = logging.getLogger(__name__)


class Command(Enum):
    """워커 스레드에 전달하는 명령."""
    STOP = auto()


class BookingResult(Enum):
    """예약 결과."""
    SUCCESS = auto()
    FAILED = auto()
    LOGIN_ERROR = auto()
    BROWSER_ERROR = auto()


class MonitorScheduler:
    """Playwright 전용 워커 스레드에서 모니터링 + 자동 예약을 수행한다.

    GUI 메인 스레드와 콜백으로 통신한다.
    Playwright 인스턴스는 워커 스레드에서만 접근한다.
    """

    def __init__(self):
        self._cmd_queue: queue.Queue = queue.Queue()
        self._worker: threading.Thread | None = None
        self._running = False
        self._interval = 60

        # 콜백 (GUI에서 설정, GUI 스레드에서 호출됨)
        self.on_check_result = None   # (available: list|None, facility: str) -> None
        self.on_booking_result = None  # (result: BookingResult, detail: str) -> None
        self.on_status_change = None   # (status: str) -> None
        self.on_error = None           # (error: Exception) -> None

    @property
    def is_running(self) -> bool:
        return self._running

    def start(self, interval_seconds: int, yeonsu_gbn: str, target_dates: list[str],
              username: str, password: str):
        """모니터링 시작."""
        if self._running:
            logger.warning("스케줄러가 이미 실행 중입니다.")
            return

        self._interval = interval_seconds
        self._running = True
        self._yeonsu_gbn = yeonsu_gbn
        self._target_dates = target_dates
        self._username = username
        self._password = password

        # 큐 비우기
        while not self._cmd_queue.empty():
            try:
                self._cmd_queue.get_nowait()
            except queue.Empty:
                break

        self._worker = threading.Thread(target=self._worker_loop, daemon=True)
        self._worker.start()
        logger.info("스케줄러 시작 (간격: %ds)", interval_seconds)

    def stop(self):
        """모니터링 중지."""
        self._running = False
        self._cmd_queue.put(Command.STOP)
        logger.info("스케줄러 중지")

    def _worker_loop(self):
        """워커 스레드 메인 루프. Playwright 세션을 소유한다."""
        session = BrowserSession()
        try:
            self._notify_status("로그인 중...")
            session.start(self._username, self._password)
            self._notify_status("모니터링 중")

            # 첫 체크 바로 실행
            self._do_check_and_book(session)

            # 주기적 체크
            while self._running:
                try:
                    cmd = self._cmd_queue.get(timeout=self._interval)
                    if cmd == Command.STOP:
                        break
                except queue.Empty:
                    pass  # 타임아웃 = 다음 체크 시간

                if not self._running:
                    break

                self._do_check_and_book(session)

        except LoginError as exc:
            logger.error("로그인 실패: %s", exc)
            if self.on_error:
                self.on_error(exc)
            self._notify_booking_result(BookingResult.LOGIN_ERROR, str(exc))
        except BrowserNotFoundError as exc:
            logger.error("브라우저 없음: %s", exc)
            if self.on_error:
                self.on_error(exc)
            self._notify_booking_result(BookingResult.BROWSER_ERROR, str(exc))
        except Exception as exc:
            logger.error("워커 스레드 오류: %s", exc)
            if self.on_error:
                self.on_error(exc)
        finally:
            session.stop()
            self._running = False

    def _do_check_and_book(self, session: BrowserSession):
        """한 번의 확인 + 조건 충족 시 예약 시도."""
        if not self._running:
            return

        self._notify_status("모니터링 중")

        if not self._target_dates:
            logger.warning("확인할 날짜가 없습니다 (체크인/체크아웃 확인 필요)")
            return

        try:
            available = session.check(self._yeonsu_gbn, self._target_dates)
        except LoginError:
            raise
        except Exception as exc:
            logger.warning("확인 실패: %s", exc)
            if self.on_check_result:
                self.on_check_result(None, self._yeonsu_gbn)
            return

        if self.on_check_result:
            self.on_check_result(available, self._yeonsu_gbn)

        if available is None:
            return

        # 전체 범위가 다 비어야 예약 시도
        if set(available) != set(self._target_dates):
            return

        # 전체 범위 예약 가능! 예약 시도
        logger.info("전체 범위 예약 가능! 예약 시도...")
        self._notify_status("예약 시도 중")

        book_date = self._target_dates[0]
        max_retries = 2

        for attempt in range(1, max_retries + 1):
            try:
                logger.info("[예약 시도 %d/%d] 날짜: %s", attempt, max_retries, book_date)
                success = session.book(self._yeonsu_gbn, book_date)
                if success:
                    logger.info("예약 성공!")
                    self._notify_status("예약 완료")
                    self._notify_booking_result(BookingResult.SUCCESS, book_date)
                    self._running = False
                    return
            except BookingError as exc:
                logger.warning("[예약 실패 %d/%d] %s", attempt, max_retries, exc)
                if attempt < max_retries:
                    time.sleep(3)

        # 모든 재시도 실패
        logger.warning("예약 재시도 모두 실패, 모니터링 계속")
        self._notify_status("모니터링 중")
        self._notify_booking_result(BookingResult.FAILED, book_date)

    def _notify_status(self, status: str):
        if self.on_status_change:
            self.on_status_change(status)

    def _notify_booking_result(self, result: BookingResult, detail: str):
        if self.on_booking_result:
            self.on_booking_result(result, detail)
