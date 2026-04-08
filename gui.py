"""CustomTkinter GUI: 설정, 상태, 로그, 자동 예약."""

import logging
import time
import tkinter as tk
from datetime import date, datetime, timedelta
from tkinter import messagebox

import customtkinter as ctk
from tkcalendar import Calendar

import config
import notifier
from checker import date_range
from facilities import get_facility_code, get_facility_names
from notifier import SLACK_WEBHOOK_URL
from scheduler import MonitorScheduler, BookingResult

# 테마 설정
ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

# 통일 서체
FONT_FAMILY = "맑은 고딕"
FONT = (FONT_FAMILY, 13)
FONT_SMALL = (FONT_FAMILY, 12)
FONT_LOG = ("맑은 고딕", 12)

# 상태별 색상
STATUS_COLORS = {
    "대기 중": "#888888",
    "로그인 중...": "#FF9800",
    "모니터링 중": "#4CAF50",
    "예약 시도 중": "#FF9800",
    "예약 완료": "#4CAF50",
    "예약 실패": "#E74C3C",
    "중지됨": "#888888",
}


class DatePicker(ctk.CTkFrame):
    """날짜 선택 위젯 (tkcalendar 팝업 사용)."""

    def __init__(self, master, on_date_selected=None, **kwargs):
        super().__init__(master, **kwargs)
        self._var = tk.StringVar()
        self._popup = None
        self._on_date_selected = on_date_selected

        self._entry = ctk.CTkEntry(self, textvariable=self._var, width=120, state="readonly", font=FONT)
        self._entry.pack(side="left")
        self._btn = ctk.CTkButton(self, text="▼", width=30, command=self._toggle, font=FONT)
        self._btn.pack(side="left", padx=(4, 0))

        self.set_date(date.today())

    def _toggle(self):
        if self._popup and self._popup.winfo_exists():
            self._popup.destroy()
            self._popup = None
            return
        self._open()

    def _open(self):
        top = tk.Toplevel(self)
        top.overrideredirect(True)
        top.lift()
        self._popup = top

        try:
            current = datetime.strptime(self._var.get(), "%Y-%m-%d").date()
        except ValueError:
            current = date.today()

        cal = Calendar(
            top,
            selectmode="day",
            locale="ko_KR",
            showweeknumbers=False,
            date_pattern="yyyy-mm-dd",
            firstweekday="sunday",
            year=current.year,
            month=current.month,
            day=current.day,
            font=(FONT_FAMILY, 12),
        )
        cal.pack(padx=4, pady=4)

        def on_select(event=None):
            self._var.set(cal.get_date())
            top.grab_release()
            top.destroy()
            self._popup = None
            if self._on_date_selected:
                self._on_date_selected(self.get_date())

        cal.bind("<<CalendarSelected>>", on_select)

        self.update_idletasks()
        x = self._btn.winfo_rootx()
        y = self._btn.winfo_rooty() + self._btn.winfo_height() + 2
        top.geometry(f"+{x}+{y}")
        top.focus_set()
        top.grab_set()

        def _close_popup(event=None):
            if self._popup:
                self._popup.grab_release()
                self._popup.destroy()
                self._popup = None

        top.bind("<Escape>", _close_popup)
        top.protocol("WM_DELETE_WINDOW", _close_popup)

    def get_date(self) -> date:
        try:
            return datetime.strptime(self._var.get(), "%Y-%m-%d").date()
        except ValueError:
            return date.today()

    def set_date(self, value):
        if isinstance(value, datetime):
            value = value.date()
        self._var.set(value.strftime("%Y-%m-%d"))


class GUILogHandler(logging.Handler):
    """로그를 CTkTextbox에 출력하는 핸들러."""

    def __init__(self, text_widget: ctk.CTkTextbox):
        super().__init__()
        self._widget = text_widget
        self._last_emit_time: float = 0

    def emit(self, record):
        msg = self.format(record)
        now = time.time()
        gap = now - self._last_emit_time if self._last_emit_time else 0
        self._last_emit_time = now

        def _append():
            self._widget.configure(state="normal")
            # 마지막 로그로부터 60초 이상 경과 시 빈 줄 삽입
            if gap >= 60:
                self._widget.insert("end", "\n")
            self._widget.insert("end", msg + "\n")
            self._widget.see("end")
            self._widget.configure(state="disabled")

        self._widget.after(0, _append)


class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("서울특별시 연수원 자동 예약")
        self.geometry("520x620")
        self.minsize(480, 540)

        self._settings = config.load()
        self._scheduler = MonitorScheduler()

        # 스케줄러 콜백 설정
        self._scheduler.on_check_result = self._on_check_result
        self._scheduler.on_booking_result = self._on_booking_result
        self._scheduler.on_status_change = self._on_status_change
        self._scheduler.on_error = self._on_scheduler_error

        self._build_ui()
        self._setup_logging()
        self._load_settings_to_ui()
        self._bind_clipboard()

        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _bind_clipboard(self):
        """macOS Cmd+C/V/A/X 클립보드 바인딩 (Tk 9.0 호환)

        Tk 9.0에서 Command+키 조합의 keysym이 '??'로 인식되는
        버그를 우회하기 위해 state(0x0008=Meta) + char로 직접 매칭한다.
        """
        def _on_key(event):
            # 0x0008 = Meta(Command) modifier
            if not (event.state & 0x0008):
                return
            ch = event.char.lower()
            w = event.widget

            # tk.Text (CTkTextbox 내부) 처리
            if isinstance(w, tk.Text):
                if ch == "c":
                    try:
                        self.clipboard_clear()
                        self.clipboard_append(w.get("sel.first", "sel.last"))
                    except tk.TclError:
                        pass
                    return "break"
                if ch == "a":
                    w.tag_add("sel", "1.0", "end")
                    return "break"
                return

            # tk.Entry (CTkEntry 내부) 처리
            if not isinstance(w, tk.Entry):
                return
            if ch == "v":
                try:
                    text = self.clipboard_get()
                except tk.TclError:
                    return "break"
                if w.select_present():
                    w.delete("sel.first", "sel.last")
                w.insert("insert", text)
                return "break"
            if ch == "c":
                if w.select_present():
                    self.clipboard_clear()
                    self.clipboard_append(w.selection_get())
                return "break"
            if ch == "x":
                if w.select_present():
                    self.clipboard_clear()
                    self.clipboard_append(w.selection_get())
                    w.delete("sel.first", "sel.last")
                return "break"
            if ch == "a":
                w.select_range(0, "end")
                w.icursor("end")
                return "break"

        self.bind_all("<Key>", _on_key)

    def _build_ui(self):
        # 탭 뷰
        self._tabview = ctk.CTkTabview(self, height=260)
        self._tabview.pack(fill="x", padx=10, pady=(10, 5))
        self._tabview.add("설정")
        self._tabview.add("안내")
        # 탭 버튼 서체 통일 (private API — CustomTkinter 업데이트 시 변경 가능)
        try:
            self._tabview._segmented_button.configure(font=FONT)
        except AttributeError:
            pass

        self._build_settings_tab()
        self._build_about_tab()
        self._build_status_bar()
        self._build_control_buttons()
        self._build_log_area()

    def _build_settings_tab(self):
        frame = self._tabview.tab("설정")

        # 아이디
        ctk.CTkLabel(frame, text="아이디", font=FONT).grid(row=0, column=0, sticky="w", padx=10, pady=6)
        self._username_var = tk.StringVar()
        ctk.CTkEntry(frame, textvariable=self._username_var, width=200, font=FONT).grid(
            row=0, column=1, sticky="w", padx=10, pady=6
        )

        # 비밀번호
        ctk.CTkLabel(frame, text="비밀번호", font=FONT).grid(row=1, column=0, sticky="w", padx=10, pady=6)
        pw_frame = ctk.CTkFrame(frame, fg_color="transparent")
        pw_frame.grid(row=1, column=1, sticky="w", padx=10, pady=6)

        self._password_var = tk.StringVar()
        self._pw_entry = ctk.CTkEntry(pw_frame, textvariable=self._password_var, width=200, show="*", font=FONT)
        self._pw_entry.pack(side="left")

        self._pw_show_var = tk.BooleanVar(value=False)
        ctk.CTkCheckBox(
            pw_frame, text="보기", variable=self._pw_show_var,
            command=self._toggle_pw_visibility, width=50, font=FONT,
        ).pack(side="left", padx=(8, 0))

        # 연수원
        ctk.CTkLabel(frame, text="연수원", font=FONT).grid(row=2, column=0, sticky="w", padx=10, pady=6)
        self._facility_var = tk.StringVar()
        ctk.CTkComboBox(
            frame,
            variable=self._facility_var,
            values=get_facility_names(),
            width=200,
            state="readonly",
            font=FONT,
            dropdown_font=FONT,
        ).grid(row=2, column=1, sticky="w", padx=10, pady=6)

        # 체크인
        ctk.CTkLabel(frame, text="체크인", font=FONT).grid(row=3, column=0, sticky="w", padx=10, pady=6)
        self._checkin_entry = DatePicker(frame, on_date_selected=self._on_checkin_selected, fg_color="transparent")
        self._checkin_entry.grid(row=3, column=1, sticky="w", padx=10, pady=6)

        # 체크아웃
        ctk.CTkLabel(frame, text="체크아웃", font=FONT).grid(row=4, column=0, sticky="w", padx=10, pady=6)
        self._checkout_entry = DatePicker(frame, fg_color="transparent")
        self._checkout_entry.grid(row=4, column=1, sticky="w", padx=10, pady=6)

        # 확인 간격
        ctk.CTkLabel(frame, text="확인 간격 (초)", font=FONT).grid(row=5, column=0, sticky="w", padx=10, pady=6)
        self._interval_var = tk.IntVar(value=60)
        ctk.CTkEntry(frame, textvariable=self._interval_var, width=80, font=FONT).grid(
            row=5, column=1, sticky="w", padx=10, pady=6
        )

        frame.columnconfigure(1, weight=1)

    def _toggle_pw_visibility(self):
        self._pw_entry.configure(show="" if self._pw_show_var.get() else "*")

    def _on_checkin_selected(self, selected_date: date):
        """체크인 날짜 선택 시 체크아웃을 다음날로 자동 설정."""
        self._checkout_entry.set_date(selected_date + timedelta(days=1))

    def _build_about_tab(self):
        frame = self._tabview.tab("안내")
        info_text = (
            "서울특별시 연수원 자동 예약 v3.0\n"
            " - 개발: kilga\n\n"
            "이 프로그램은 서울특별시 연수원 예약 사이트의 예약 가능 날짜를 주기적으로 확인하고,\n"
            "전체 범위가 비어있으면 자동으로 예약까지 완료합니다.\n\n"
            "[사용 방법]\n"
            "1. '설정' 탭에서 아이디, 비밀번호, 연수원, 체크인/체크아웃, 확인간격을 설정\n"
            "2. [시작] 버튼을 누르면 자동으로 모니터링 + 예약 진행\n"
            "3. 예약 완료 시 Slack으로 알림을 보내고 자동 정지\n"
            "4. 예약 실패 시 Slack 알림 후 모니터링 계속"
        )
        ctk.CTkLabel(frame, text=info_text, justify="left", wraplength=450, anchor="nw", font=FONT_SMALL).pack(
            fill="both", expand=True, padx=12, pady=12
        )

    def _build_status_bar(self):
        """상태 표시 바."""
        self._status_frame = ctk.CTkFrame(self)
        self._status_frame.pack(fill="x", padx=10, pady=(0, 5))

        self._status_dot = ctk.CTkLabel(self._status_frame, text="●", font=(FONT_FAMILY, 14))
        self._status_dot.pack(side="left", padx=(10, 6))

        self._status_label = ctk.CTkLabel(self._status_frame, text="대기 중", font=FONT)
        self._status_label.pack(side="left")

        self._update_status_display("대기 중")

    def _build_control_buttons(self):
        frame = ctk.CTkFrame(self, fg_color="transparent")
        frame.pack(fill="x", padx=10, pady=(0, 5))

        self._start_btn = ctk.CTkButton(frame, text="시작", command=self._on_start, width=90, font=FONT)
        self._start_btn.pack(side="left", padx=4)

        self._stop_btn = ctk.CTkButton(
            frame, text="중지", command=self._on_stop, width=90,
            fg_color="#E74C3C", hover_color="#C0392B", state="disabled", font=FONT,
        )
        self._stop_btn.pack(side="left", padx=4)

        ctk.CTkButton(
            frame, text="로그 지우기", command=self._clear_log, width=90,
            fg_color="gray30", hover_color="gray40", font=FONT,
        ).pack(side="right", padx=4)

        ctk.CTkButton(
            frame, text="Slack 테스트", command=self._test_slack, width=100,
            fg_color="gray30", hover_color="gray40", font=FONT,
        ).pack(side="right", padx=4)

    def _build_log_area(self):
        self._log_text = ctk.CTkTextbox(self, state="disabled", font=FONT_LOG)
        self._log_text.pack(fill="both", expand=True, padx=10, pady=(0, 10))

    def _clear_log(self):
        self._log_text.configure(state="normal")
        self._log_text.delete("1.0", "end")
        self._log_text.configure(state="disabled")

    def _setup_logging(self):
        fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", "%H:%M:%S")
        handler = GUILogHandler(self._log_text)
        handler.setFormatter(fmt)
        root_logger = logging.getLogger()
        root_logger.setLevel(logging.INFO)
        root_logger.addHandler(handler)

    def _load_settings_to_ui(self):
        settings = self._settings
        self._username_var.set(settings.get("username", ""))
        pw_encoded = settings.get("password", "")
        if pw_encoded:
            self._password_var.set(config.decode_password(pw_encoded))
        if settings.get("facility"):
            self._facility_var.set(settings["facility"])
        for key, entry in [("checkin", self._checkin_entry), ("checkout", self._checkout_entry)]:
            value = settings.get(key, "")
            if value:
                try:
                    entry.set_date(datetime.strptime(value, "%Y-%m-%d").date())
                except ValueError:
                    pass
        self._interval_var.set(settings.get("interval_seconds", 60))

    def _collect_settings(self) -> dict:
        return {
            "username": self._username_var.get().strip(),
            "password": config.encode_password(self._password_var.get().strip()),
            "facility": self._facility_var.get(),
            "checkin": self._checkin_entry.get_date().strftime("%Y-%m-%d"),
            "checkout": self._checkout_entry.get_date().strftime("%Y-%m-%d"),
            "interval_seconds": self._interval_var.get(),
        }

    def _save_settings(self):
        self._settings = self._collect_settings()
        config.save(self._settings)

    def _update_status_display(self, status: str):
        """상태 표시를 업데이트한다."""
        color = STATUS_COLORS.get(status, "#888888")
        self._status_dot.configure(text_color=color)
        self._status_label.configure(text=status)

    def _on_start(self):
        self._save_settings()
        settings = self._settings

        if not settings["username"] or not settings["password"]:
            messagebox.showwarning("입력 오류", "아이디와 비밀번호를 입력해 주세요.")
            return
        if not settings["facility"]:
            messagebox.showwarning("입력 오류", "연수원을 선택해 주세요.")
            return
        if settings["checkin"] >= settings["checkout"]:
            messagebox.showwarning("입력 오류", "체크아웃 날짜는 체크인 다음날 이후여야 합니다.")
            return

        self._clear_log()
        self._start_btn.configure(state="disabled")
        self._stop_btn.configure(state="normal")
        self._update_status_display("로그인 중...")
        self.update_idletasks()

        # 체크인~체크아웃 전날까지 날짜 범위
        try:
            checkin_date = datetime.strptime(settings["checkin"], "%Y-%m-%d").date()
            checkout_date = datetime.strptime(settings["checkout"], "%Y-%m-%d").date()
        except ValueError:
            messagebox.showerror("오류", "날짜 형식이 올바르지 않습니다.")
            return

        actual_end = (checkout_date - timedelta(days=1)).strftime("%Y-%m-%d")
        target_dates = date_range(checkin_date.strftime("%Y-%m-%d"), actual_end)
        yeonsu_gbn = get_facility_code(settings["facility"]) or ""

        if not yeonsu_gbn:
            messagebox.showerror("오류", f"연수원 코드를 찾을 수 없습니다: {settings['facility']}")
            return

        username = settings["username"]
        password = config.decode_password(settings["password"])

        logging.info(
            "요청자: %s | %s | 체크인/아웃: %s ~ %s",
            username, settings["facility"],
            settings["checkin"][5:], settings["checkout"][5:],
        )

        self._scheduler.start(
            interval_seconds=settings["interval_seconds"],
            yeonsu_gbn=yeonsu_gbn,
            target_dates=target_dates,
            username=username,
            password=password,
        )

    def _on_stop(self):
        self._scheduler.stop()
        self._start_btn.configure(state="normal")
        self._stop_btn.configure(state="disabled")
        self._update_status_display("중지됨")

    def _test_slack(self):
        ok = notifier.send_test_notification(SLACK_WEBHOOK_URL)
        if ok:
            messagebox.showinfo("성공", "Slack 테스트 메시지 전송 성공!")
        else:
            messagebox.showerror("실패", "Slack 메시지 전송 실패.")

    # --- 스케줄러 콜백 (워커 스레드에서 호출됨, after로 GUI 스레드 전환) ---

    def _on_check_result(self, available, facility_code):
        """모니터링 확인 결과 콜백."""
        def _update():
            if available is None:
                return
            facility_name = self._settings.get("facility", facility_code)
            if not available:
                logging.info("[%s] 예약 가능 날짜 없음", facility_name)
        self.after(0, _update)

    def _on_booking_result(self, result: BookingResult, detail: str):
        """예약 결과 콜백."""
        def _update():
            settings = self._settings
            facility_name = settings.get("facility", "")
            username = settings.get("username", "")

            if result == BookingResult.SUCCESS:
                self._update_status_display("예약 완료")
                self._start_btn.configure(state="normal")
                self._stop_btn.configure(state="disabled")
                notifier.send_booking_success(
                    SLACK_WEBHOOK_URL,
                    facility_name, detail,
                    username=username,
                    checkin=settings.get("checkin", ""),
                    checkout=settings.get("checkout", ""),
                )
            elif result == BookingResult.FAILED:
                self._update_status_display("모니터링 중")
            elif result == BookingResult.LOGIN_ERROR:
                self._update_status_display("예약 실패")
                self._start_btn.configure(state="normal")
                self._stop_btn.configure(state="disabled")
                messagebox.showerror("로그인 실패", detail)
            elif result == BookingResult.BROWSER_ERROR:
                self._update_status_display("예약 실패")
                self._start_btn.configure(state="normal")
                self._stop_btn.configure(state="disabled")
                messagebox.showerror("브라우저 없음", detail)
        self.after(0, _update)

    def _on_status_change(self, status: str):
        """상태 변경 콜백."""
        self.after(0, lambda: self._update_status_display(status))

    def _on_scheduler_error(self, error: Exception):
        """스케줄러 오류 콜백."""
        def _update():
            self._start_btn.configure(state="normal")
            self._stop_btn.configure(state="disabled")
            self._update_status_display("예약 실패")
        self.after(0, _update)

    def _on_close(self):
        self._save_settings()
        self._scheduler.stop()
        self.destroy()
