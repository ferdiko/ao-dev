"""
User identity management.

The local user's UUID is stored in SOVARA_HOME/.user_id.
User data (full_name, email) lives in the database's users table.
"""

import os
import threading
import uuid

from sovara.common.config import _ask_field, green
from sovara.common.constants import USER_ID_PATH


_USER_ID_UNSET = object()
_cached_user_id: object | str | None = _USER_ID_UNSET
_user_id_lock = threading.Lock()


def invalidate_user_id_cache() -> None:
    global _cached_user_id
    with _user_id_lock:
        _cached_user_id = _USER_ID_UNSET


def read_user_id() -> str | None:
    """Read user UUID from SOVARA_HOME/.user_id. Returns None if not configured."""
    global _cached_user_id
    with _user_id_lock:
        if _cached_user_id is not _USER_ID_UNSET:
            return _cached_user_id  # type: ignore[return-value]
    if not os.path.isfile(USER_ID_PATH):
        with _user_id_lock:
            _cached_user_id = None
        return None
    with open(USER_ID_PATH, encoding="utf-8") as f:
        user_id = f.read().strip()
    cached = user_id if user_id else None
    with _user_id_lock:
        _cached_user_id = cached
    return cached


def write_user_id(user_id: str) -> None:
    """Write user UUID to SOVARA_HOME/.user_id."""
    global _cached_user_id
    os.makedirs(os.path.dirname(USER_ID_PATH), exist_ok=True)
    with open(USER_ID_PATH, "w", encoding="utf-8") as f:
        f.write(user_id + "\n")
    with _user_id_lock:
        _cached_user_id = user_id


def _prompt_user_metadata(existing: dict = None) -> tuple[str, str]:
    """Prompt for full name and email. Shows existing values in green if provided."""
    if existing:
        print(f"Full name: {green(existing['full_name'])}")
        full_name = _ask_field("> ", str, default=existing["full_name"])
        print(f"Email: {green(existing['email'])}")
        email = _ask_field("> ", str, default=existing["email"])
    else:
        full_name = _ask_field("Full name\n> ", str)
        email = _ask_field("Email\n> ", str)
    return full_name, email


def setup_user_interactive(existing: dict = None) -> dict:
    """Prompt user for full name and email. Returns dict with user_id, full_name, email.

    If existing is provided (from DB), shows current values in green as defaults.
    If not, generates a new UUID and writes it to disk.
    """
    full_name, email = _prompt_user_metadata(existing)
    if existing:
        user_id = existing["user_id"]
    else:
        user_id = str(uuid.uuid4())
        write_user_id(user_id)
    return {"user_id": user_id, "full_name": full_name, "email": email}


def _notify_running_server_about_user_change() -> None:
    """Best-effort nudge so an already-open UI refreshes local user state."""
    try:
        from sovara.cli.so_server import _server_http_request

        _server_http_request("POST", "/ui/refresh-user", timeout=0.25)
    except Exception:
        pass


def ensure_user_configured() -> dict:
    """Return user dict, prompting interactively if not yet configured.

    Checks SOVARA_HOME/.user_id for UUID, then fetches from DB. If either is missing,
    prompts the user and writes both the .user_id file and DB record.
    """
    from sovara.server.database_manager import DB

    user_id = read_user_id()
    if user_id:
        row = DB.get_user(user_id)
        if row:
            return {"user_id": user_id, "full_name": row["full_name"], "email": row["email"]}
        # .user_id file exists but no DB entry — keep UUID, ask for metadata
        print("Sovara user identity found but not yet configured.\n")
        full_name, email = _prompt_user_metadata()
        user = {"user_id": user_id, "full_name": full_name, "email": email}
    else:
        from sovara.common.constants import WELCOME_ART
        print(WELCOME_ART)
        print("Welcome to Sovara! Let's set up your identity.\n")
        user = setup_user_interactive()

    DB.upsert_user(user["user_id"], user["full_name"], user["email"])
    _notify_running_server_about_user_change()
    return user
