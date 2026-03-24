import contextvars
import threading
from contextlib import contextmanager
import json
from sovara.server.database_manager import DB
from sovara.common.utils import http_post
from sovara.common.logger import logger


# Process's session id stored as parent_session_id. Subruns have their own
# session_id and current_session_id maps thread -> session_id.
current_session_id = contextvars.ContextVar("session_id", default=None)
parent_session_id = None

# Names of all subruns in the process. Used to ensure they are unique.
run_names = None
_run_names_lock = threading.Lock()


def get_run_name(run_name):
    # Run names must be unique for a given parent_session_id.
    with _run_names_lock:
        if run_name not in run_names:
            run_names.add(run_name)
            return run_name

        i = 1
        while f"{run_name} ({i})" in run_names:
            i += 1

        run_name = f"{run_name} ({i})"
        run_names.add(run_name)
        return run_name


@contextmanager
def sovara_launch(run_name="Workflow run"):
    """
    Context manager for launching runs with a specific name.
    NOTE: Upon rerun of one subrun, we rerun all subruns. Other
    subruns' expensive calls should be cached though.
    """
    # Get unique run name.
    run_name = get_run_name(run_name)

    # Get rerun environment from parent
    parent_env = DB.get_parent_environment(parent_session_id)

    # If rerun, get previous's runs session_id, else None.
    prev_session_id = DB.get_subrun_id(parent_session_id, run_name)

    # Register new subrun with server via HTTP.
    response = http_post("/runner/subrun", {
        "name": run_name,
        "parent_session_id": parent_session_id,
        "cwd": parent_env["cwd"],
        "command": parent_env["command"],
        "environment": json.loads(parent_env["environment"]),
        "prev_session_id": prev_session_id,
    })
    session_id = response["session_id"]
    current_session_id.set(session_id)

    try:
        # Run user code
        yield run_name
    finally:
        # Deregister (best-effort -- don't crash user code if server is down)
        try:
            http_post("/runner/deregister", {"session_id": session_id})
        except Exception as e:
            logger.warning(f"Failed to deregister subrun {session_id}: {e}")


def log(entry=None, success=None):
    # Validate input types
    if entry is not None and not isinstance(entry, str):
        raise TypeError(f"`entry` must be a string, got {type(entry).__name__}")
    if success is not None and not isinstance(success, bool):
        raise TypeError(f"`success` must be a boolean or None, got {type(success).__name__}")

    try:
        http_post("/runner/log", {"session_id": get_session_id(), "success": success, "entry": entry})
    except Exception as e:
        logger.warning(f"Failed to send log: {e}")


def get_session_id():
    sid = current_session_id.get()
    if sid is None:
        # Fall back to parent_session_id for worker threads where
        # the context var may not have been properly inherited
        sid = parent_session_id
    return sid


def set_parent_session_id(session_id):
    # Called by agent_runner: set session id of `so-record`
    global parent_session_id, current_session_id, run_names
    parent_session_id = session_id
    current_session_id.set(session_id)
    run_names = set(DB.get_session_name(parent_session_id))
