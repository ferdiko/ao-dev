import os
import shutil
import pytest

from ao.common.project import write_project_config

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
AO_DIR = os.path.join(REPO_ROOT, ".ao")


@pytest.fixture(autouse=True, scope="session")
def ensure_test_project():
    """Create a temporary .ao/config.json at repo root so ao-record works in tests."""
    already_existed = os.path.isdir(AO_DIR)
    if not already_existed:
        write_project_config(REPO_ROOT, {
            "project_id": "test-project",
            "name": "ao-test",
            "description": "",
        })
    yield
    if not already_existed:
        shutil.rmtree(AO_DIR, ignore_errors=True)
