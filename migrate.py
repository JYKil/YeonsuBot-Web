"""기존 단일 settings.json을 사용자별 설정 위치로 이전하는 일회성 스크립트."""

import json
import time
from pathlib import Path

import config


def _next_migrated_path(settings_file: Path) -> Path:
    timestamp = int(time.time())
    migrated_path = settings_file.with_name(f"settings.json.migrated.{timestamp}")
    while migrated_path.exists():
        timestamp += 1
        migrated_path = settings_file.with_name(f"settings.json.migrated.{timestamp}")
    return migrated_path


def main() -> int:
    base_dir = config.base_dir
    settings_file = base_dir / "settings.json"
    migrated_files = sorted(base_dir.glob("settings.json.migrated.*"))

    if migrated_files:
        print(f"skip: migrated settings already exist under {base_dir}")
        for migrated_file in migrated_files:
            print(f"  - {migrated_file}")
        return 0

    if not settings_file.exists():
        print(f"skip: {settings_file} does not exist")
        return 0

    with settings_file.open("r", encoding="utf-8") as f:
        settings = json.load(f)

    username = settings.get("username")
    if not isinstance(username, str) or not username:
        print(f"error: {settings_file} has no valid username")
        return 1

    config.save(username, settings)

    migrated_path = _next_migrated_path(settings_file)
    settings_file.rename(migrated_path)
    print(f"migrated: {settings_file} -> {migrated_path}")
    print(f"saved: {config.USERS_DIR / username / 'settings.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
