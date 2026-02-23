"""Load test: 20 parallel ao-record sessions hitting the server concurrently."""

import os
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from ao.server.database_manager import DB


PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def restart_server():
    """Clear server state for a clean test."""
    subprocess.run(["uv", "run", "--directory", PROJECT_DIR, "ao-server", "clear"], check=False)


def run_ao_record(script_path: str, index: int) -> tuple[int, int]:
    """Run ao-record in a subprocess. Returns (index, return_code)."""
    env = os.environ.copy()
    env["AO_NO_DEBUG_MODE"] = "True"
    result = subprocess.run(
        ["uv", "run", "--directory", PROJECT_DIR, "ao-record", script_path],
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    return index, result.returncode


class TestLoad:
    """Stress-test the server with 20 concurrent ao-record sessions."""

    def test_20_parallel_sessions(self, tmp_path):
        # 1. Restart server, snapshot existing experiment count
        restart_server()
        DB.switch_mode("local")
        existing = len(DB.get_all_experiments_sorted())

        # 2. Write trivial dummy script
        script = tmp_path / "dummy.py"
        script.write_text("import time; time.sleep(0.5)\n")

        # 3. Launch 20 ao-record subprocesses in parallel
        n = 20
        results = {}
        with ThreadPoolExecutor(max_workers=n) as pool:
            futures = {
                pool.submit(run_ao_record, str(script), i): i for i in range(n)
            }
            for future in as_completed(futures):
                idx, rc = future.result()
                results[idx] = rc

        # 4. Assert all exited with code 0
        failures = {i: rc for i, rc in results.items() if rc != 0}
        assert not failures, f"Processes failed: {failures}"
        assert len(results) == n

        # 5. Assert DB gained exactly 20 new experiments with unique session IDs
        experiments = DB.get_all_experiments_sorted()
        new_count = len(experiments) - existing
        assert new_count == n, f"Expected {n} new experiments, got {new_count}"
        session_ids = [exp["session_id"] for exp in experiments]
        assert len(set(session_ids)) == len(session_ids), "Duplicate session IDs found"
