import contextvars
import threading
import time
from contextlib import contextmanager
import json
from sovara.server.database_manager import DB
from sovara.common.logger import logger
from sovara.common.utils import http_post
from sovara.common.custom_metrics import MetricsPayload


# Process's run id stored as parent_run_id. Subruns have their own
# run_id and current_run_id maps thread -> run_id.
current_run_id = contextvars.ContextVar("run_id", default=None)
parent_run_id = None

# Names of all subruns in the process. Used to ensure they are unique.
run_names = None
_run_names_lock = threading.Lock()
_run_timer_starts: dict[str, float] = {}
_run_timer_lock = threading.Lock()


def get_run_name(run_name):
    # Run names must be unique for a given parent_run_id.
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


def start_run_timer(run_id):
    if not run_id:
        return
    with _run_timer_lock:
        _run_timer_starts[run_id] = time.perf_counter()


def clear_run_timer(run_id):
    if not run_id:
        return
    with _run_timer_lock:
        _run_timer_starts.pop(run_id, None)


def reset_current_run_timer():
    start_run_timer(get_run_id())


def get_run_runtime_seconds(run_id=None):
    resolved_run_id = run_id or get_run_id()
    if not resolved_run_id:
        return None
    with _run_timer_lock:
        started_at = _run_timer_starts.get(resolved_run_id)
    if started_at is None:
        return None
    return max(0.0, time.perf_counter() - started_at)


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
    parent_env = DB.get_parent_environment(parent_run_id)

    # If rerun, get previous's runs run_id, else None.
    prev_run_id = DB.get_subrun_id(parent_run_id, run_name)

    # Register new subrun with server via HTTP.
    response = http_post("/runner/subrun", {
        "name": run_name,
        "parent_run_id": parent_run_id,
        "cwd": parent_env["cwd"],
        "command": parent_env["command"],
        "environment": json.loads(parent_env["environment"]),
        "prev_run_id": prev_run_id,
    })
    run_id = response["run_id"]
    current_run_id.set(run_id)
    start_run_timer(run_id)

    try:
        # Run user code
        yield run_name
    finally:
        # Deregister (best-effort -- don't crash user code if server is down)
        try:
            http_post("/runner/deregister", {"run_id": run_id}, timeout=0.5)
        except Exception as e:
            logger.warning(f"Failed to deregister subrun {run_id}: {e}")
        finally:
            clear_run_timer(run_id)


def log(**metrics):
    payload = MetricsPayload(metrics=metrics)
    try:
        http_post("/runner/log", {"run_id": get_run_id(), "metrics": payload.metrics})
    except Exception as e:
        logger.warning(f"Failed to send metrics: {e}")


def get_run_id():
    sid = current_run_id.get()
    if sid is None:
        # Fall back to parent_run_id for worker threads where
        # the context var may not have been properly inherited
        sid = parent_run_id
    return sid


def set_parent_run_id(run_id):
    # Called by agent_runner: set run id of `so-record`
    global parent_run_id, current_run_id, run_names
    parent_run_id = run_id
    current_run_id.set(run_id)
    start_run_timer(run_id)
    run_names = set(DB.get_run_name(parent_run_id))
