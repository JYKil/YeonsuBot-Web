"""Playwright 전용 워커 스레드 + 주기적 모니터링 스케줄러."""

import logging
import threading
from datetime import datetime, timedelta
from enum import Enum, auto

import notifier
from checker import BrowserSession, BookingError, LoginError, BrowserNotFoundError
from facilities import get_facility_name

logger = logging.getLogger(__name__)


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

  각 start() 호출마다 새 threading.Event를 생성하여 워커에 전달한다.
  이전 워커의 finally 블록이 새 워커의 _running 플래그를 덮어쓰는
  경쟁 조건을 방지한다.
  """

  def __init__(self):
    self._worker: threading.Thread | None = None
    self._stop_event: threading.Event | None = None
    self._running = False
    self._interval = 60
    self._cycle_count = 0  # 현재 세션의 누적 체크 사이클 수

    # 콜백 (GUI/웹 서버에서 설정, 워커 스레드에서 호출됨)
    self.on_check_result = None   # (available: list|None, facility: str) -> None
    self.on_booking_result = None  # (result: BookingResult, detail: str) -> None
    self.on_status_change = None   # (status: str) -> None
    self.on_error = None           # (error: Exception) -> None
    self.on_cycle_start = None     # (cycle: int) -> None, 매 체크 사이클 진입 시

  @property
  def is_running(self) -> bool:
    return self._running

  def start(self, interval_seconds: int, yeonsu_gbn: str, target_dates: list[str],
            username: str, password: str):
    """모니터링 시작."""
    if self._running:
      logger.warning("스케줄러가 이미 실행 중입니다.")
      return

    # 이전 워커 스레드 종료 신호 + 대기
    if self._stop_event:
      self._stop_event.set()
    if self._worker and self._worker.is_alive():
      logger.info("이전 워커 스레드 종료 대기...")
      self._worker.join(timeout=10)

    self._interval = interval_seconds
    self._running = True
    self._cycle_count = 0  # 새 세션마다 리셋
    self._yeonsu_gbn = yeonsu_gbn
    self._target_dates = target_dates
    self._username = username
    self._password = password

    # 새 세대의 중지 이벤트 생성
    self._stop_event = threading.Event()
    stop_event = self._stop_event  # 워커에 전달할 로컬 참조

    self._worker = threading.Thread(
      target=self._worker_loop,
      args=(stop_event,),
      daemon=True,
    )
    self._worker.start()
    logger.info("스케줄러 시작 (간격: %ds)", interval_seconds)

  def stop(self):
    """모니터링 중지."""
    self._running = False
    if self._stop_event:
      self._stop_event.set()
    logger.info("스케줄러 중지")

  def _worker_loop(self, stop_event: threading.Event):
    """워커 스레드 메인 루프. Playwright 세션을 소유한다."""
    session = BrowserSession()
    try:
      self._notify_status("로그인 중...")
      session.start(self._username, self._password)
      self._notify_status("모니터링 중")

      # 첫 체크 바로 실행
      self._do_check_and_book(session, stop_event)

      # 주기적 체크
      while not stop_event.is_set():
        # interval 동안 대기하되, 중지 신호가 오면 즉시 깨어남
        stop_event.wait(timeout=self._interval)
        if stop_event.is_set():
          break
        self._do_check_and_book(session, stop_event)

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
      # 현재 세대의 이벤트인 경우에만 _running 해제
      # (새 start()가 이미 호출되었으면 건드리지 않음)
      if self._stop_event is stop_event:
        self._running = False

  def _do_check_and_book(self, session: BrowserSession, stop_event: threading.Event):
    """한 번의 확인 + 조건 충족 시 예약 시도."""
    if stop_event.is_set():
      return

    self._cycle_count += 1
    if self.on_cycle_start:
      try:
        self.on_cycle_start(self._cycle_count)
      except Exception as exc:
        logger.warning("on_cycle_start 콜백 오류: %s", exc)

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
      logger.info("다음 점검까지 %d초 대기", self._interval)
      return

    # 전체 범위가 다 비어야 예약 시도
    if set(available) != set(self._target_dates):
      logger.info("일부 날짜 불가, 다음 점검까지 %d초 대기", self._interval)
      return

    # 전체 범위 예약 가능! 예약 시도
    logger.info("전체 범위 예약 가능! 예약 시도...")
    self._notify_status("예약 시도 중")

    import time
    max_retries = 2

    for attempt in range(1, max_retries + 1):
      if stop_event.is_set():
        return
      try:
        logger.info("[예약 시도 %d/%d] 날짜: %s", attempt, max_retries, self._target_dates)
        success = session.book(self._yeonsu_gbn, self._target_dates, stop_event=stop_event)
        if success:
          logger.info("예약 성공!")
          # UI 버튼 즉시 토글을 위해 _running 선반영 (finally에서 session.stop()이
          # 브라우저 정리하는 동안 UI가 STOP 상태로 남지 않도록)
          self._running = False
          self._send_slack_success()
          self._notify_status("중지됨")
          self._notify_booking_result(BookingResult.SUCCESS, self._target_dates[0])
          stop_event.set()  # 예약 성공 시 루프 종료
          return
      except BookingError as exc:
        logger.warning("[예약 실패 %d/%d] %s", attempt, max_retries, exc)
        if attempt < max_retries:
          if stop_event.wait(3):
            return  # 중지 신호 수신

    # 모든 재시도 실패 — Slack 실패 알림은 생략 (사용자 요청)
    logger.warning("예약 재시도 모두 실패, 모니터링 계속")
    if not stop_event.is_set():
      self._notify_status("모니터링 중")
    self._notify_booking_result(BookingResult.FAILED, self._target_dates[0])

  def _send_slack_success(self):
    try:
      notifier.send_booking_success(
        notifier.SLACK_WEBHOOK_URL,
        facility_name=get_facility_name(self._yeonsu_gbn),
        booked_date=self._target_dates[0],
        username=self._username,
        checkin=self._target_dates[0],
        checkout=(datetime.strptime(self._target_dates[-1], "%Y%m%d") + timedelta(days=1)).strftime("%Y%m%d"),
      )
    except Exception as exc:
      logger.warning("Slack 성공 알림 실패: %s", exc)

  def _notify_status(self, status: str):
    if self.on_status_change:
      self.on_status_change(status)

  def _notify_booking_result(self, result: BookingResult, detail: str):
    if self.on_booking_result:
      self.on_booking_result(result, detail)
