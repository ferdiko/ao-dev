import os
from datetime import datetime, timezone
from sovara.server.database_manager import DB


def cleanup_test_db():
    """Clean up test data from the database and environment."""
    # Clear attachment records
    DB.execute("DELETE FROM attachments")

    # Clean up environment variables
    if "SOVARA_SESSION_ID" in os.environ:
        del os.environ["SOVARA_SESSION_ID"]


def restart_server():
    """Restart the server to ensure clean state for tests."""
    import subprocess
    import time

    subprocess.run(["so-server", "restart"], check=False)
    time.sleep(1)


def setup_test_session(session_id, name="Test Session", parent_session_id=None):
    """
    Helper to create necessary database records for testing.

    Args:
        session_id: The session ID to create
        name: Name for the test session
        parent_session_id: Parent session ID (defaults to session_id if None)
    """
    DB.add_experiment(
        session_id=session_id,
        name=name,
        timestamp=datetime.now(timezone.utc),
        cwd=os.getcwd(),
        command="test",
        environment={"TEST": "true"},
        parent_session_id=parent_session_id or session_id,
    )
