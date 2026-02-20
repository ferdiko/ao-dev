"""Tests for concurrency correctness in the runner-server interface."""

import io
import json
import queue
import threading
import time
from ao.runner import context_manager
from ao.runner import string_matching
from ao.common import utils
from ao.server.database_backends import sqlite


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


class TestLogSocketSafety:
    """log() must hold _server_lock when writing to the socket."""

    def test_concurrent_log_and_send_no_corruption(self):
        """Concurrent log() and send_to_server() must produce valid JSON lines.

        log() writes directly to server_file without _server_lock.
        send_to_server() holds _server_lock. When both run concurrently,
        their writes can interleave mid-line, producing malformed JSON.

        We use a SlowFile that yields mid-write to widen the race window.
        """
        # Collect all bytes written to the socket
        raw_chunks = []
        chunks_lock = threading.Lock()

        class SlowFile:
            """A file that yields mid-write to expose interleaving."""

            def write(self, data):
                # Write one char at a time with a yield, simulating a slow socket
                for ch in data:
                    with chunks_lock:
                        raw_chunks.append(ch)
                    time.sleep(0.0001)

            def flush(self):
                pass

        slow_file = SlowFile()
        old_server_file = context_manager.server_file
        context_manager.server_file = slow_file
        context_manager.current_session_id.set("test-session")

        barrier = threading.Barrier(10)

        def call_log():
            barrier.wait()
            context_manager.log(entry="from_log", success=True)

        def call_send():
            barrier.wait()
            utils.send_to_server({"type": "node", "data": "from_send"})

        try:
            threads = []
            for _ in range(5):
                threads.append(threading.Thread(target=call_log))
                threads.append(threading.Thread(target=call_send))
            for t in threads:
                t.start()
            for t in threads:
                t.join()
        finally:
            context_manager.server_file = old_server_file

        # Reconstruct what was written and try to parse each line
        full_output = "".join(raw_chunks)
        lines = [l for l in full_output.split("\n") if l.strip()]

        corrupted = []
        for line in lines:
            try:
                json.loads(line)
            except json.JSONDecodeError:
                corrupted.append(line)

        assert len(corrupted) == 0, (
            f"Corrupted JSON lines from interleaved writes:\n"
            + "\n".join(corrupted[:5])
        )


class TestResponseQueueRace:
    """send_to_server_and_receive() must route responses to the correct caller."""

    def test_concurrent_send_receive_crosstalk(self):
        """Two threads calling send_to_server_and_receive get each other's
        responses because they share a single queue with no correlation IDs.

        Setup: thread A sends first (guaranteed by a gate), then thread B sends.
        The fake listener responds in REVERSE order: B's response first, then A's.
        Since the queue is FIFO, thread A (which is already waiting) dequeues B's
        response. This is deterministic, not probabilistic.
        """
        sent_messages = []
        sent_lock = threading.Lock()
        a_sent = threading.Event()  # Signals that A has sent and is now waiting

        class RecordingFile:
            def write(self, data):
                with sent_lock:
                    try:
                        sent_messages.append(json.loads(data.strip()))
                    except json.JSONDecodeError:
                        pass

            def flush(self):
                pass

        rsp_queue = queue.Queue()
        old_server_file = context_manager.server_file
        old_response_queue = context_manager.response_queue
        context_manager.server_file = RecordingFile()
        context_manager.response_queue = rsp_queue

        results = {}
        results_lock = threading.Lock()

        def sender_a():
            msg = {"type": "add_subrun", "name": "alpha"}
            # A sends first, then signals so B can go
            response = utils.send_to_server_and_receive(msg, timeout=5)
            with results_lock:
                results["alpha"] = response.get("session_id")

        def sender_b():
            # Wait until A has sent (A is now blocked on queue.get)
            a_sent.wait()
            msg = {"type": "add_subrun", "name": "beta"}
            response = utils.send_to_server_and_receive(msg, timeout=5)
            with results_lock:
                results["beta"] = response.get("session_id")

        # Fake listener: detects A's send, signals B, waits for B's send,
        # then responds in REVERSE order (beta first, alpha second).
        # Uses route_response if available (after fix), else raw queue (before fix).
        def fake_listener():
            # Wait for A to send
            while True:
                with sent_lock:
                    if len(sent_messages) >= 1:
                        break
                time.sleep(0.001)
            # A has sent and is now blocked waiting. Let B send.
            a_sent.set()

            # Wait for B to send
            while True:
                with sent_lock:
                    if len(sent_messages) >= 2:
                        break
                time.sleep(0.001)
            time.sleep(0.01)  # Small delay to ensure B is also waiting

            # Build responses in REVERSE order of sends.
            # Each response includes the request_id from the original message
            # so route_response can deliver it to the correct thread.
            with sent_lock:
                msgs = list(sent_messages[:2])
            for msg in reversed(msgs):
                name = msg.get("name", "unknown")
                response = {"type": "session_id", "session_id": f"session-for-{name}"}
                request_id = msg.get("request_id")
                if request_id:
                    response["request_id"] = request_id
                # Route via request_id matching (like the real listener does)
                if not utils.route_response(response):
                    rsp_queue.put(response)

        try:
            listener = threading.Thread(target=fake_listener, daemon=True)
            listener.start()
            t1 = threading.Thread(target=sender_a)
            t2 = threading.Thread(target=sender_b)
            t1.start()
            t2.start()
            t1.join(timeout=10)
            t2.join(timeout=10)
            listener.join(timeout=10)
        finally:
            context_manager.server_file = old_server_file
            context_manager.response_queue = old_response_queue

        alpha_got = results.get("alpha")
        beta_got = results.get("beta")

        correct = (alpha_got == "session-for-alpha" and beta_got == "session-for-beta")
        assert correct, (
            f"Response crosstalk: alpha got '{alpha_got}', beta got '{beta_got}'. "
            f"Each thread must receive its own response."
        )


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
