from __future__ import annotations

import os
import stat
import sys
from pathlib import Path

APP_UID = 10001
APP_GID = 10001


def prepare_sqlite_directory(raw_path: str) -> None:
    database = Path(raw_path).expanduser()
    if not database.is_absolute():
        database = (Path("/app/backend") / database).resolve()
    parent = database.parent
    parent.mkdir(parents=True, exist_ok=True)

    if os.geteuid() == 0:
        os.chown(parent, APP_UID, APP_GID)
        os.chmod(parent, 0o700)
        allowed_names = {
            database.name,
            database.name + "-wal",
            database.name + "-shm",
            database.name + "-journal",
        }
        for item in parent.iterdir():
            if item.name not in allowed_names:
                continue
            try:
                mode = item.lstat().st_mode
                if stat.S_ISREG(mode):
                    os.chown(item, APP_UID, APP_GID, follow_symlinks=False)
                    os.chmod(item, 0o600, follow_symlinks=False)
            except FileNotFoundError:
                pass
    elif not os.access(parent, os.W_OK):
        raise RuntimeError(f"SQLite directory is not writable by UID {os.geteuid()}: {parent}")


def main() -> None:
    for variable in ("SESSION_DB_PATH", "AUTH_DB_PATH"):
        value = os.getenv(variable)
        if value:
            prepare_sqlite_directory(value)

    command = sys.argv[1:] or [
        "python",
        "-m",
        "uvicorn",
        "app.main:app",
        "--host",
        "0.0.0.0",
    ]
    if "uvicorn" in command and "--port" not in command:
        command.extend(["--port", os.getenv("PORT", "8000")])

    if os.geteuid() == 0:
        os.setgroups([])
        os.setgid(APP_GID)
        os.setuid(APP_UID)

    os.execvp(command[0], command)


if __name__ == "__main__":
    main()
