"""
Tests for cache consistency.

These tests verify that:
1. LLM calls are properly cached and replayed on re-runs
2. Graph topology is preserved across runs
3. Node IDs remain consistent for cache hits
"""

import asyncio
import pytest

try:
    from tests.billable.caching_utils import run_test, caching_asserts, RunData
except ImportError:
    from caching_utils import run_test, caching_asserts, RunData


def _deepresearch_asserts(run_data_obj: RunData):
    """Check that every node has at least one parent node, except GPT-4.1 and first o3."""
    target_nodes = {edge["target_uuid"] for edge in run_data_obj.graph["edges"]}
    first_o3_found = False

    for node in run_data_obj.graph["nodes"]:
        node_uuid = node["uuid"]
        label = node.get("label", "")

        # Skip check for "gpt-4.1" nodes
        if label == "GPT-4.1":
            continue

        # Skip check for the first "o3" node only
        if label == "o3" and not first_o3_found:
            first_o3_found = True
            continue

        # All other nodes must have at least one parent
        assert (
            node_uuid in target_nodes
        ), f"[DeepResearch] Node {node_uuid} with label '{label}' has no parent nodes"


@pytest.mark.parametrize(
    "script_path",
    [
        "./example_workflows/debug_examples/langchain/agent.py",
        "./example_workflows/debug_examples/langchain/async_agent.py",
        "./example_workflows/debug_examples/langchain/simple_chat.py",
        "./example_workflows/debug_examples/together/debate.py",
        "./example_workflows/debug_examples/anthropic/async_debate.py",
        "./example_workflows/debug_examples/anthropic/debate.py",
        "./example_workflows/debug_examples/mcp/simple_test.py",
        "./example_workflows/debug_examples/subruns/multiple_runs_asyncio.py",
        "./example_workflows/debug_examples/subruns/multiple_runs_sequential.py",
        "./example_workflows/debug_examples/subruns/multiple_runs_threading.py",
        "./example_workflows/debug_examples/openai/async_debate.py",
        "./example_workflows/debug_examples/openai/debate.py",
        "./example_workflows/debug_examples/openai/chat.py",
        "./example_workflows/debug_examples/openai/chat_async.py",
        "./example_workflows/debug_examples/openai/tool_call.py",
        "./example_workflows/debug_examples/google/debate.py",
        "./example_workflows/debug_examples/google/debate_async.py",
    ],
)
def test_debug_examples(script_path: str):
    run_data_obj = asyncio.run(run_test(script_path=script_path))
    caching_asserts(run_data_obj)


def test_deepresearch():
    run_data_obj = asyncio.run(
        run_test(script_path="./example_workflows/miroflow_deep_research/single_task.py")
    )
    caching_asserts(run_data_obj)
    _deepresearch_asserts(run_data_obj)


if __name__ == "__main__":
    test_deepresearch()
