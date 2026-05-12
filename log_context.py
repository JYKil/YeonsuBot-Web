"""스케줄러 워커 로그를 사용자 컨텍스트에 연결한다."""

from contextvars import ContextVar


USER_CTX: ContextVar[str | None] = ContextVar("yeonsubot_user", default=None)
