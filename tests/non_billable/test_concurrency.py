"""Tests for concurrency correctness in the runner-server interface."""

import threading
import time
from sovara.runner import context_manager
from sovara.runner import string_matching
from sovara.server.database_backends import sqlite


class SlowSet(set):
    """A set that yields between __contains__ check and return, widening race windows."""

    def __contains__(self, item):
        result = super().__contains__(item)
        if not result:
            time.sleep(0.001)  # Yield between check and add
        return result


class TestRunNamesRace:
    """get_run_name() must return unique names under concurrent access."""

    def test_concurrent_same_name(self):
        """20 threads requesting 'eval' simultaneously must each get a unique name.

        The race in get_run_name is a classic TOCTOU: check (`not in`) then act (`add`).
        Under CPython's GIL, plain set operations are nearly atomic, so we use a
        SlowSet that yields between the check and return to widen the window.
        """
        context_manager.run_names = SlowSet()
        results = []
        lock = threading.Lock()
        barrier = threading.Barrier(20)

        def request_name():
            barrier.wait()
            name = context_manager.get_run_name("eval")
            with lock:
                results.append(name)

        threads = [threading.Thread(target=request_name) for _ in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(results) == 20
        assert len(set(results)) == 20, f"Duplicate names: {results}"


class SlowDict(dict):
    """A dict whose .items() iteration yields between elements, widening the
    race window for concurrent modification.

    Uses the live dict view (not a snapshot) so insertions during iteration
    trigger RuntimeError: dictionary changed size during iteration.
    """

    def items(self):
        view = super().items()
        for item in view:
            time.sleep(0.001)
            yield item


class TestSessionDataThreadSafety:
    """_session_outputs must be safe under concurrent read+write."""

    def test_concurrent_iterate_and_write(self):
        """One thread iterates _session_outputs (as find_source_nodes does)
        while another writes to it (as store_output_strings does).

        With a plain dict and a SlowDict wrapper, the writer inserts keys
        during iteration, triggering RuntimeError.

        The fix: find_source_nodes snapshots under _session_lock, store_output_strings
        writes under _session_lock. Verify this lock-protected pattern works.
        """
        session_id = "test-race"

        # Pre-populate with some data so iteration has something to walk over
        slow = SlowDict()
        for i in range(10):
            slow[f"existing-{i}"] = [["word1", "word2", "word3"]]
        string_matching._session_outputs[session_id] = slow

        errors = []
        barrier = threading.Barrier(2)

        def reader():
            """Snapshot under lock then iterate (like find_source_nodes does)."""
            barrier.wait()
            try:
                with string_matching._session_lock:
                    outputs = dict(string_matching._get_session_outputs(session_id))
                for node_id, word_lists in outputs.items():
                    for wl in word_lists:
                        _ = len(wl)
            except RuntimeError as e:
                errors.append(e)

        def writer():
            """Write under lock (like store_output_strings does)."""
            barrier.wait()
            for i in range(10):
                with string_matching._session_lock:
                    outputs = string_matching._get_session_outputs(session_id)
                    outputs[f"new-{i}"] = [["hello", "world"]]
                time.sleep(0.0005)

        try:
            t1 = threading.Thread(target=reader)
            t2 = threading.Thread(target=writer)
            t1.start()
            t2.start()
            t1.join()
            t2.join()
        finally:
            string_matching._session_outputs.pop(session_id, None)

        assert len(errors) == 0, (
            f"RuntimeError during concurrent dict access: {errors[0]}"
        )


class TestOccurrenceCounter:
    """Concurrent identical cache lookups must each get a distinct row."""

    def test_concurrent_identical_lookups_get_distinct_rows(self):
        """5 threads calling get_in_out with the same (session_id, input_hash)
        must each get a different cached row, not all the same first row.

        Without the occurrence counter, all threads hit offset 0 and get
        the same node_id. With it, each gets a unique offset (0-4).
        """
        from sovara.server.database_manager import DB

        session_id = "test-occurrence"
        input_hash = "deadbeef"

        # Insert 5 rows with the same (session_id, input_hash) but different node_ids
        for i in range(5):
            sqlite.execute(
                "INSERT OR IGNORE INTO llm_calls (session_id, input_hash, node_id, api_type) "
                "VALUES (?, ?, ?, ?)",
                (session_id, input_hash, f"node-{i}", "test"),
            )

        DB._occurrence_counters.clear()

        node_ids = []
        lock = threading.Lock()
        barrier = threading.Barrier(5)

        def lookup():
            barrier.wait()
            occurrence = DB._next_occurrence(session_id, input_hash)
            row = sqlite.get_llm_call_by_session_and_hash_query(
                session_id, input_hash, offset=occurrence,
            )
            with lock:
                node_ids.append(row["node_id"] if row else None)

        threads = [threading.Thread(target=lookup) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Clean up
        sqlite.execute("DELETE FROM llm_calls WHERE session_id=?", (session_id,))
        DB._occurrence_counters.clear()

        assert len(node_ids) == 5
        assert None not in node_ids, f"Some lookups got no row: {node_ids}"
        assert len(set(node_ids)) == 5, (
            f"Expected 5 distinct node_ids, got {node_ids}. "
            f"Concurrent identical lookups returned the same cached row."
        )


class TestSQLitePerThreadConnections:
    """SQLite must use per-thread connections, not a single shared connection."""

    def test_threads_get_distinct_connections(self):
        """Each thread must get its own SQLite connection.

        With a shared _shared_conn, all threads get the same connection object,
        serializing all DB operations behind _db_lock. With per-thread connections
        (threading.local), each thread gets its own connection and readers can
        run concurrently via WAL mode.
        """
        connection_ids = []
        lock = threading.Lock()
        barrier = threading.Barrier(5)

        def get_connection():
            barrier.wait()
            conn = sqlite.get_conn()
            with lock:
                connection_ids.append(id(conn))

        threads = [threading.Thread(target=get_connection) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        unique = len(set(connection_ids))
        assert unique == 5, (
            f"Expected 5 unique connections (per-thread), got {unique}. "
            f"All threads share one connection, serializing all DB I/O."
        )
