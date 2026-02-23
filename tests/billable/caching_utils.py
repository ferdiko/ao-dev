import os
import sys
import random
import json
import time
import subprocess
import re
from dataclasses import dataclass
from ao.server.database_manager import DB


@dataclass
class RunData:
    rows: list
    new_rows: list
    graph: list
    new_graph: list


def print_graph(graph: dict, label: str) -> None:
    """Print graph topology for debugging."""
    print("\n" + "=" * 60)
    print(f"{label}:")
    print(f"  Nodes ({len(graph['nodes'])}):")
    for node in graph["nodes"]:
        print(f"    - {node['id']}: {node.get('type', 'unknown')}")
    print(f"  Edges ({len(graph['edges'])}):")
    for edge in graph["edges"]:
        print(f"    - {edge['source']} -> {edge['target']}")
    print("=" * 60 + "\n")


def restart_server():
    """Clear server state to ensure clean state for tests."""
    subprocess.run(["ao-server", "clear"], check=False)


def _run_script_with_ao_record(script_path: str, env: dict) -> tuple[int, str]:
    """
    Run a script using ao-record via uv and return (return_code, session_id).

    Uses `uv run --directory <provider_dir> ao-record <script_name>` to run
    the script in its provider-specific uv environment.

    Parses the session_id from the runner's output.
    """
    env["AO_NO_DEBUG_MODE"] = "True"
    env["PYTHONUNBUFFERED"] = "1"  # Ensure output isn't buffered

    # Extract directory and script name for uv run
    script_dir = os.path.dirname(os.path.abspath(script_path))
    script_name = os.path.basename(script_path)

    proc = subprocess.Popen(
        ["uv", "run", "--directory", script_dir, "ao-record", script_name],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )

    output_lines = []
    session_id = None

    # Read output and look for session_id
    for line in proc.stdout:
        output_lines.append(line)
        # Print all output for debugging
        print(line, end="", flush=True)
        # Look for session_id in log output
        if "session_id:" in line or "Registered with session_id:" in line:
            # Extract session_id from line like "Registered with session_id: abc123"
            match = re.search(r"session_id[:\s]+([a-f0-9-]+)", line, re.IGNORECASE)
            if match:
                session_id = match.group(1)

    proc.wait()
    return proc.returncode, session_id


async def run_test(script_path: str):
    """
    Run a test script twice using ao-record and return data for caching validation.

    This function:
    1. Restarts the server for clean state
    2. Runs the script once via ao-record
    3. Captures LLM calls and graph topology
    4. Runs the script again (should use cached results)
    5. Captures LLM calls and graph again
    6. Returns both sets of data for comparison
    """
    # Restart server to ensure clean state for this test
    restart_server()

    # Set up environment
    env = os.environ.copy()
    ao_random_seed = random.randint(0, 2**31 - 1)
    env["AO_SEED"] = str(ao_random_seed)

    # Ensure we use local SQLite database
    DB.switch_mode("local")

    # First run
    print("\n" + "=" * 60)
    print("STARTING FIRST RUN")
    print("=" * 60)
    return_code, session_id = _run_script_with_ao_record(script_path, env)
    assert return_code == 0, f"First run failed with return_code {return_code}"
    assert session_id is not None, "Could not extract session_id from first run output"

    # Query results from first run
    rows = DB.query_all(
        "SELECT node_id, input_overwrite, output FROM llm_calls WHERE session_id=?",
        (session_id,),
    )

    graph_topology = DB.query_one(
        "SELECT log, success, graph_topology FROM experiments WHERE session_id=?",
        (session_id,),
    )
    graph = json.loads(graph_topology["graph_topology"])
    print_graph(graph, "FIRST RUN GRAPH")

    # Wait a moment before second run
    time.sleep(1)

    # Second run (should use cached results)
    # Pass the same session_id so it reuses the cache
    print("\n" + "=" * 60)
    print("STARTING SECOND RUN (should use cache)")
    print("=" * 60)
    env["AO_SESSION_ID"] = session_id
    returncode_rerun, _ = _run_script_with_ao_record(script_path, env)
    assert returncode_rerun == 0, f"Re-run failed with return_code {returncode_rerun}"

    # Query results from second run
    new_rows = DB.query_all(
        "SELECT node_id, input_overwrite, output FROM llm_calls WHERE session_id=?",
        (session_id,),
    )

    new_graph_topology = DB.query_one(
        "SELECT log, success, graph_topology FROM experiments WHERE session_id=?",
        (session_id,),
    )
    new_graph = json.loads(new_graph_topology["graph_topology"])
    print_graph(new_graph, "SECOND RUN GRAPH")

    run_data_obj = RunData(rows=rows, new_rows=new_rows, graph=graph, new_graph=new_graph)

    return run_data_obj


def caching_asserts(run_data_obj: RunData):
    assert len(run_data_obj.rows) == len(
        run_data_obj.new_rows
    ), "Length of LLM calls does not match after re-run"
    for old_row, new_row in zip(run_data_obj.rows, run_data_obj.new_rows):
        assert (
            old_row["node_id"] == new_row["node_id"]
        ), f"Node IDs of LLM calls don't match after re-run. Potential cache issue. Original: {len(run_data_obj.rows)}; New: {len(run_data_obj.new_rows)}"

    # Compare graph topology between runs
    assert len(run_data_obj.graph["nodes"]) == len(
        run_data_obj.new_graph["nodes"]
    ), f"Number of nodes in graph topology doesn't match after re-run. {len(run_data_obj.graph["nodes"])}; New:{len(run_data_obj.new_graph["nodes"])}"
    assert len(run_data_obj.graph["edges"]) == len(
        run_data_obj.new_graph["edges"]
    ), f"Number of edges in graph topology doesn't match after re-run. Original: {len(run_data_obj.graph["edges"])}; New: {len(run_data_obj.new_graph["edges"])}\n\n"

    # Check that node IDs match between the two graphs
    original_node_ids = {node["id"] for node in run_data_obj.graph["nodes"]}
    new_node_ids = {node["id"] for node in run_data_obj.new_graph["nodes"]}
    assert original_node_ids == new_node_ids, "Node IDs in graph topology don't match after re-run"

    # Check that edge structure is identical
    original_edges = {(edge["source"], edge["target"]) for edge in run_data_obj.graph["edges"]}
    new_edges = {(edge["source"], edge["target"]) for edge in run_data_obj.new_graph["edges"]}
    assert (
        original_edges == new_edges
    ), f"Edge structure in graph topology doesn't match after re-run.\noriginal: {original_edges}\n\nnew: {new_edges}"
