"""설정 저장/불러오기 (사용자별 settings.json)"""

import base64
import json
import os
import re
import sys
from pathlib import Path

# SETTINGS_DIR 환경변수가 있으면 우선 사용 (Docker 볼륨 마운트)
_env_dir = os.environ.get("SETTINGS_DIR")
if _env_dir:
    base_dir = Path(_env_dir)
elif getattr(sys, 'frozen', False):
    base_dir = Path(sys.executable).resolve().parent / "data"
else:
    base_dir = Path(__file__).resolve().parent / "data"

USERS_DIR = base_dir / "users"

DEFAULTS = {
    "username": "",
    "password": "",
    "facility": "",
    "checkin": "",
    "checkout": "",
    "interval_seconds": 60,
}


def _user_dir(username: str) -> Path:
    if not re.match(r"^(?!\.{1,2}$)[A-Za-z0-9_.-]+$", username):
        raise ValueError("Invalid username")
    return USERS_DIR / username


def load(username: str) -> dict:
    settings_file = _user_dir(username) / "settings.json"
    if not settings_file.exists():
        return DEFAULTS.copy()
    try:
        with settings_file.open("r", encoding="utf-8") as f:
            data = json.load(f)
        merged = DEFAULTS.copy()
        merged.update(data)
        return merged
    except Exception:
        return DEFAULTS.copy()


def save(username: str, settings: dict):
    data = {k: v for k, v in settings.items() if k in DEFAULTS}
    user_dir = _user_dir(username)
    user_dir.mkdir(parents=True, exist_ok=True)
    settings_file = user_dir / "settings.json"
    with settings_file.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def encode_password(password: str) -> str:
    return base64.b64encode(password.encode("utf-8")).decode("ascii")


def decode_password(encoded: str) -> str:
    try:
        return base64.b64decode(encoded.encode("ascii")).decode("utf-8")
    except Exception:
        return ""
