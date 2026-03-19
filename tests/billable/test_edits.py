"""
Tests for cache edit functionality.

Verifies that editing a cached input causes a cache miss by measuring runtime.
"""

import copy
import json
import os
import subprocess
import threading
import time

import websocket

from ao.common.constants import HOST, PORT


class NodeTimingListener:
    """Connect to server as UI and measure time between first/last node arrivals."""

    def __init__(self):
        self.first_node_time = None
        self.last_node_time = None
        self.node_count = 0
        self.last_node_id = None  # Track last node for editing
        self.last_node_input = None  # Track last node's input dict for editing
        self.session_id = None  # Track session for editing
        self._lock = threading.Lock()
        self._stop = False
        self._ws = None
        self._thread = None

    def start(self):
        """Connect to server via WebSocket and start listening in background thread."""
        self._ws = websocket.WebSocket()
        self._ws.connect(f"ws://{HOST}:{PORT}/ws")
        # Read initial config message from server
        self._ws.recv()

        self._thread = threading.Thread(target=self._listen, daemon=True)
        self._thread.start()

    def _listen(self):
        """Background thread: listen for graph_update messages."""
        self._ws.settimeout(0.1)
        while not self._stop:
            try:
                data = self._ws.recv()
                msg = json.loads(data)
                if msg.get("type") == "graph_update":
                    self._on_graph_update(msg)
            except websocket.WebSocketTimeoutException:
                continue
            except Exception:
                break

    def _on_graph_update(self, msg):
        """Record timing and last node when nodes arrive."""
        now = time.time()
        with self._lock:
            payload = msg.get("payload", {})
            nodes = payload.get("nodes", [])
            if nodes:
                if self.first_node_time is None:
                    self.first_node_time = now
                self.last_node_time = now
                self.node_count = len(nodes)
                # Track the last node for editing
                last_node = nodes[-1]
                self.last_node_id = last_node.get("id")
                # Parse and store the input dict for editing
                input_str = last_node.get("input")
                if input_str:
                    self.last_node_input = json.loads(input_str)
            # Track session_id
            if msg.get("session_id"):
                self.session_id = msg.get("session_id")

    def get_elapsed(self) -> float:
        """Return elapsed time (last - first node) without stopping."""
        with self._lock:
            if self.first_node_time and self.last_node_time:
                return self.last_node_time - self.first_node_time
            return 0.0

    def send_edit(self):
        """Send edit_input message to server for the last node.

        Finds the field containing "Consider the following two paragraphs:" and replaces it
        with "EDITED PROMPT" to trigger a cache miss.
        """
        with self._lock:
            if not self.last_node_id or not self.session_id or not self.last_node_input:
                raise ValueError("No node to edit - run a script first")

            # Deep copy to avoid modifying the original
            input_dict = copy.deepcopy(self.last_node_input)

            # Recursively find and edit the field containing the prompt
            def edit_prompt_field(obj):
                if isinstance(obj, dict):
                    for key, value in obj.items():
                        if isinstance(value, str) and "Consider the following two paragraphs:" in value:
                            obj[key] = "EDITED PROMPT"
                            return True
                        if isinstance(value, (dict, list)) and edit_prompt_field(value):
                            return True
                elif isinstance(obj, list):
                    for i, item in enumerate(obj):
                        if isinstance(item, str) and "Consider the following two paragraphs:" in item:
                            obj[i] = "EDITED PROMPT"
                            return True
                        if isinstance(item, (dict, list)) and edit_prompt_field(item):
                            return True
                return False

            if not edit_prompt_field(input_dict):
                raise ValueError("Could not find prompt field to edit")

            edit_msg = {
                "type": "edit_input",
                "session_id": self.session_id,
                "node_id": self.last_node_id,
                "value": json.dumps(input_dict),
            }
        self._ws.send(json.dumps(edit_msg))
        time.sleep(0.5)  # Give server time to process

    def stop(self):
        """Stop listening and close connection."""
        self._stop = True
        if self._thread:
            self._thread.join(timeout=2)
        if self._ws:
            self._ws.close()

    def reset(self):
        """Reset timing for next run (keep node info for editing)."""
        with self._lock:
            self.first_node_time = None
            self.last_node_time = None
            self.node_count = 0


def run_and_measure_node_timing(
    script_path: str, listener: NodeTimingListener, session_id: str = None
) -> tuple:
    """
    Run script via ao-record while measuring node arrival timing.
    Returns (session_id, elapsed_seconds_between_first_and_last_node).
    """
    listener.reset()

    env = os.environ.copy()
    env["AO_NO_DEBUG_MODE"] = "True"
    if session_id:
        env["AO_SESSION_ID"] = session_id

    script_dir = os.path.dirname(os.path.abspath(script_path))
    script_name = os.path.basename(script_path)

    result = subprocess.run(
        ["uv", "run", "--directory", script_dir, "ao-record", script_name],
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )

    if result.returncode != 0:
        print(f"STDOUT: {result.stdout}")
        print(f"STDERR: {result.stderr}")
        raise RuntimeError(f"Script failed with return code {result.returncode}")

    # Small delay to ensure all messages are received
    time.sleep(0.5)

    elapsed = listener.get_elapsed()
    # session_id is tracked by listener from graph_update messages
    return listener.session_id, elapsed


def test_cache_edit_timing():
    """
    Test that editing a cached input causes a cache miss by measuring runtime.

    Measure time between receiving first add_node to last add_node msg.
    I.e., for 4 API calls, we measure runtime between last 3.
    - Run 1: All API calls (no cache) - measure baseline time T
    - Run 2: All cached - should be ≤10% of T
    - Run 3: Edit last node - should be ~1/3 of T (between 1/9 and 5/9)
    """
    script_path = "./example_workflows/debug_examples/anthropic/debate.py"

    # Start listening for node messages
    listener = NodeTimingListener()
    listener.start()

    try:
        # Run 1: No cache (real API calls)
        session_id, time_no_cache = run_and_measure_node_timing(script_path, listener)
        print("0/3 cache:", time_no_cache)

        # Run 2: All cached
        _, time_all_cached = run_and_measure_node_timing(script_path, listener, session_id)
        print("3/3 cache hits:", time_all_cached)

        assert time_all_cached <= time_no_cache * 0.1, (
            f"Cached run should be ≤10% of uncached. "
            f"Got {time_all_cached:.2f}s vs {time_no_cache:.2f}s"
        )

        # Edit the last node (send via UI connection, no DB access needed)
        listener.send_edit()

        # Run 3: One node needs real API call
        _, time_one_uncached = run_and_measure_node_timing(script_path, listener, session_id)
        print("2/3 cache hits", time_one_uncached)

        # Should be ~1/3 of no-cache time (between 1/9 and 5/9 with wiggle room)
        lower_bound = time_no_cache * (1 / 9)
        upper_bound = time_no_cache * (5 / 9)
        assert lower_bound <= time_one_uncached <= upper_bound, (
            f"Edited run should be between {lower_bound:.2f}s and {upper_bound:.2f}s. "
            f"Got {time_one_uncached:.2f}s"
        )
    finally:
        listener.stop()


if __name__ == "__main__":
    test_cache_edit_timing()
