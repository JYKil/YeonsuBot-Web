"""설정 저장/불러오기 (settings.json)"""

import json
import base64
import os
import sys

# SETTINGS_DIR 환경변수가 있으면 우선 사용 (Docker 볼륨 마운트)
_env_dir = os.environ.get("SETTINGS_DIR")
if _env_dir:
    base_dir = _env_dir
    os.makedirs(base_dir, exist_ok=True)
elif getattr(sys, 'frozen', False):
    base_dir = os.path.dirname(sys.executable)
else:
    base_dir = os.path.dirname(os.path.abspath(__file__))

SETTINGS_FILE = os.path.join(base_dir, "settings.json")

DEFAULTS = {
    "username": "",
    "password": "",
    "facility": "",
    "checkin": "",
    "checkout": "",
    "interval_seconds": 60,
}


def load() -> dict:
    if not os.path.exists(SETTINGS_FILE):
        return DEFAULTS.copy()
    try:
        with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        merged = DEFAULTS.copy()
        merged.update(data)
        return merged
    except Exception:
        return DEFAULTS.copy()


def save(settings: dict):
    data = {k: v for k, v in settings.items() if k in DEFAULTS}
    with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def encode_password(password: str) -> str:
    return base64.b64encode(password.encode("utf-8")).decode("ascii")


def decode_password(encoded: str) -> str:
    try:
        return base64.b64decode(encoded.encode("ascii")).decode("utf-8")
    except Exception:
        return ""
