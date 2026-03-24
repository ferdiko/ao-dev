import os
import pytest

from sovara.common.constants import TEST_USER_ID, TEST_PROJECT_ID
from sovara.server.database_manager import DB


@pytest.fixture(autouse=True, scope="session")
def ensure_test_user_and_project():
    """Ensure a test user and project exist for so-record to work in tests."""
    os.environ["_SOVARA_TESTING"] = "1"
    DB.upsert_user(TEST_USER_ID, "Test User", "test@test.com")
    DB.upsert_project(TEST_PROJECT_ID, "sovara-test", "")
    yield
    os.environ.pop("_SOVARA_TESTING", None)
    DB.delete_project(TEST_PROJECT_ID)
    DB.delete_user(TEST_USER_ID)
