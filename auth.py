"""헤더 우선, 쿠키 fallback 메모리 세션 관리."""

from __future__ import annotations

import os
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from fastapi import Cookie, HTTPException, Request


SESSION_COOKIE_NAME = "yeonsubot_session"
SESSION_TTL = timedelta(days=7)
MAX_CONCURRENT_USERS = 3


@dataclass
class SessionInfo:
    username: str
    created_at: datetime
    last_seen_at: datetime


_sessions: dict[str, SessionInfo] = {}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _purge_expired() -> None:
    """만료된 세션을 _sessions에서 제거."""
    now = _now()
    expired = [sid for sid, s in _sessions.items() if now - s.created_at > SESSION_TTL]
    for sid in expired:
        del _sessions[sid]


def create_session(username: str) -> str:
    _purge_expired()
    # 이미 로그인된 사용자는 추가 탭을 허용 (한도에 포함 안 함)
    active_users = {s.username for s in _sessions.values()}
    if username not in active_users and len(active_users) >= MAX_CONCURRENT_USERS:
        raise HTTPException(
            status_code=503,
            detail=f"현재 최대 {MAX_CONCURRENT_USERS}명이 로그인되어 있습니다. 잠시 후 다시 시도해 주세요.",
        )
    session_id = secrets.token_urlsafe(32)
    now = _now()
    _sessions[session_id] = SessionInfo(
        username=username,
        created_at=now,
        last_seen_at=now,
    )
    return session_id


def resolve_session(session_id: str | None) -> str | None:
    if not session_id:
        return None

    session = _sessions.get(session_id)
    if not session:
        return None

    now = _now()
    if now - session.created_at > SESSION_TTL:
        destroy_session(session_id)
        return None

    session.last_seen_at = now
    return session.username


def destroy_session(session_id: str) -> None:
    _sessions.pop(session_id, None)


def admin_session_snapshot() -> list[dict]:
    _purge_expired()

    grouped: dict[str, dict] = {}
    for session in _sessions.values():
        item = grouped.get(session.username)
        if item is None:
            grouped[session.username] = {
                "username": session.username,
                "session_count": 1,
                "first_created_at": session.created_at,
                "latest_created_at": session.created_at,
                "last_seen_at": session.last_seen_at,
            }
            continue

        item["session_count"] += 1
        if session.created_at < item["first_created_at"]:
            item["first_created_at"] = session.created_at
        if session.created_at > item["latest_created_at"]:
            item["latest_created_at"] = session.created_at
        if session.last_seen_at > item["last_seen_at"]:
            item["last_seen_at"] = session.last_seen_at

    return sorted(
        grouped.values(),
        key=lambda item: item["last_seen_at"],
        reverse=True,
    )


def current_admin(request: Request) -> bool:
    admin_password = os.getenv("ADMIN_PASSWORD")
    if not admin_password:
        raise HTTPException(
            status_code=503,
            detail="admin 비밀번호가 설정되지 않았습니다.",
        )

    provided_password = request.headers.get("X-YeonsuBot-Admin-Password")
    if not provided_password or not secrets.compare_digest(
        provided_password,
        admin_password,
    ):
        raise HTTPException(status_code=401, detail="admin 인증이 필요합니다.")

    return True


def current_user(
    request: Request,
    cookie_session_id: str | None = Cookie(None, alias=SESSION_COOKIE_NAME),
) -> str:
    # X-YeonsuBot-Session 헤더 우선, 없으면 쿠키 fallback
    session_id = request.headers.get("X-YeonsuBot-Session") or cookie_session_id
    username = resolve_session(session_id)
    if not username:
        raise HTTPException(status_code=401, detail="인증이 필요합니다.")
    return username


def current_user_optional(
    request: Request,
    cookie_session_id: str | None = Cookie(None, alias=SESSION_COOKIE_NAME),
) -> str | None:
    """인증이 없어도 None을 반환하는 current_user 변형 (헬스체크/공개 엔드포인트용)."""
    session_id = request.headers.get("X-YeonsuBot-Session") or cookie_session_id
    return resolve_session(session_id)
