import os
import pytest

from ao.common.constants import TEST_USER_ID, TEST_PROJECT_ID
from ao.server.database_manager import DB


@pytest.fixture(autouse=True, scope="session")
def ensure_test_user_and_project():
    """Ensure a test user and project exist for ao-record to work in tests."""
    os.environ["_AO_TESTING"] = "1"
    DB.upsert_user(TEST_USER_ID, "Test User", "test@test.com")
    DB.upsert_project(TEST_PROJECT_ID, "ao-test", "")
    yield
    os.environ.pop("_AO_TESTING", None)
