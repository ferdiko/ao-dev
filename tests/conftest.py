import os
import shutil
import tempfile
import pytest

# Important: set all Sovara test paths before importing any sovara modules.
# The constants module resolves these env vars at import time.
_TEST_SOVARA_HOME_OWNED = "SOVARA_HOME" not in os.environ
_TEST_SOVARA_HOME = (
    tempfile.mkdtemp(prefix="sovara-tests-")
    if _TEST_SOVARA_HOME_OWNED
    else os.path.abspath(os.path.expanduser(os.environ["SOVARA_HOME"]))
)
_TEST_SOVARA_CACHE = os.path.join(_TEST_SOVARA_HOME, "cache")


def _default_test_port() -> int:
    # Use a high, process-derived port so test runs do not default to the user's
    # local server port, without requiring socket bind permissions at import time.
    return 6200 + (os.getpid() % 1000)

os.environ["SOVARA_HOME"] = _TEST_SOVARA_HOME
os.environ.setdefault("SOVARA_CONFIG", os.path.join(_TEST_SOVARA_HOME, "config.yaml"))
os.environ.setdefault("SOVARA_DB_PATH", os.path.join(_TEST_SOVARA_HOME, "db"))
os.environ.setdefault("SOVARA_LOG_DIR", os.path.join(_TEST_SOVARA_HOME, "logs"))
os.environ.setdefault("SOVARA_CACHE", _TEST_SOVARA_CACHE)
os.environ.setdefault("ATTACHMENT_CACHE", os.path.join(_TEST_SOVARA_CACHE, "attachments"))
os.environ.setdefault("SOVARA_GIT_DIR", os.path.join(_TEST_SOVARA_HOME, "git"))
os.environ.setdefault("PYTHON_PORT", str(_default_test_port()))
os.environ["_SOVARA_TESTING"] = "1"

from sovara.common.constants import TEST_USER_ID, TEST_PROJECT_ID
from sovara.server.database import DB


@pytest.fixture(autouse=True, scope="session")
def ensure_test_user_and_project():
    """Ensure a test user and project exist for so-record to work in tests."""
    DB.upsert_user(TEST_USER_ID, "Test User", "test@test.com")
    DB.upsert_project(TEST_PROJECT_ID, "sovara-test", "")
    yield
    try:
        DB.delete_project(TEST_PROJECT_ID)
        DB.delete_user(TEST_USER_ID)
    finally:
        DB.clear_connections()
        if _TEST_SOVARA_HOME_OWNED:
            shutil.rmtree(_TEST_SOVARA_HOME, ignore_errors=True)
