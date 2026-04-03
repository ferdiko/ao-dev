import os
from datetime import datetime, timezone
from sovara.server.database import DB


def cleanup_test_db():
    """Clean up test data from the database and environment."""
    # Clear attachment records
    DB.execute("DELETE FROM attachments")

    # Clean up environment variables
    if "SOVARA_RUN_ID" in os.environ:
        del os.environ["SOVARA_RUN_ID"]


def restart_server():
    """Restart the server to ensure clean state for tests."""
    import subprocess
    import time

    subprocess.run(["so-server", "restart"], check=False)
    time.sleep(1)


def setup_test_run(run_id, name="Test Run", parent_run_id=None):
    """
    Helper to create necessary database records for testing.

    Args:
        run_id: The run ID to create
        name: Name for the test run
        parent_run_id: Parent run ID (defaults to run_id if None)
    """
    DB.add_run(
        run_id=run_id,
        name=name,
        timestamp=datetime.now(timezone.utc),
        cwd=os.getcwd(),
        command="test",
        environment={"TEST": "true"},
        parent_run_id=parent_run_id or run_id,
    )
