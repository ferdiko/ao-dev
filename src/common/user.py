"""
User identity management.

The local user's UUID is stored in AO_HOME/.user_id.
User data (full_name, email) lives in the database's users table.
"""

import os
import uuid

from ao.common.config import _ask_field, green
from ao.common.constants import AO_HOME

USER_ID_PATH = os.path.join(AO_HOME, ".user_id")


def read_user_id() -> str | None:
    """Read user UUID from AO_HOME/.user_id. Returns None if not configured."""
    if not os.path.isfile(USER_ID_PATH):
        return None
    with open(USER_ID_PATH, encoding="utf-8") as f:
        user_id = f.read().strip()
    return user_id if user_id else None


def write_user_id(user_id: str) -> None:
    """Write user UUID to AO_HOME/.user_id."""
    os.makedirs(os.path.dirname(USER_ID_PATH), exist_ok=True)
    with open(USER_ID_PATH, "w", encoding="utf-8") as f:
        f.write(user_id + "\n")


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


def ensure_user_configured() -> dict:
    """Return user dict, prompting interactively if not yet configured.

    Checks AO_HOME/.user_id for UUID, then fetches from DB. If either is missing,
    prompts the user and writes both the .user_id file and DB record.
    """
    from ao.server.database_manager import DB

    user_id = read_user_id()
    if user_id:
        row = DB.get_user(user_id)
        if row:
            return {"user_id": user_id, "full_name": row["full_name"], "email": row["email"]}
        # .user_id file exists but no DB entry — keep UUID, ask for metadata
        print("AO user identity found but not yet configured.\n")
        full_name, email = _prompt_user_metadata()
        user = {"user_id": user_id, "full_name": full_name, "email": email}
    else:
        from ao.common.constants import WELCOME_ART
        print(WELCOME_ART)
        print("Welcome to Sovara! Let's set up your identity.\n")
        user = setup_user_interactive()

    DB.upsert_user(user["user_id"], user["full_name"], user["email"])
    return user
