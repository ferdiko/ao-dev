"""
Patch for claude_agent_sdk to intercept message parsing.

Since the SDK spawns a subprocess (Claude CLI) and communicates via stdin/stdout,
we intercept at the message parsing level rather than HTTP. This allows us to
see each tool use, tool result, and assistant response as they stream through.
"""

from functools import wraps
import uuid
import json
from typing import List, Dict, Any

from ao.runner.monkey_patching.patching_utils import send_graph_node_and_edges, capture_stack_trace
from ao.runner.string_matching import tokenize, split_html_content, is_content_match
from ao.runner.context_manager import get_session_id
from ao.common.logger import logger


# Module-level storage for content matching (per session)
# Structure: {session_id: {node_id: [[word_lists]]}}
_sdk_session_outputs: Dict[str, Dict[str, List[List[str]]]] = {}

# Track tool_use_id -> node_id mapping so we can attach tool results to their nodes
_sdk_tool_use_to_node: Dict[str, Dict[str, str]] = {}

# Track the last tool node IDs per session for chaining (forms: Redacted → Tool → Redacted → Tool)
_sdk_last_tool_nodes: Dict[str, List[str]] = {}


def claude_sdk_patch():
    """Apply patch to claude_agent_sdk's parse_message function."""
    try:
        from claude_agent_sdk._internal import message_parser
        from claude_agent_sdk.types import (
            AssistantMessage,
            UserMessage,
            ToolUseBlock,
            ToolResultBlock,
            TextBlock,
        )
    except ImportError:
        logger.info("claude_agent_sdk not installed, skipping SDK patches")
        return

    original_parse = message_parser.parse_message

    @wraps(original_parse)
    def patched_parse_message(data: dict) -> Any:
        """Intercept message parsing to create graph nodes."""
        # Parse the message first (let SDK do its work)
        message = original_parse(data)

        # Get session context
        session_id = get_session_id()
        if not session_id:
            return message

        api_type = "claude_agent_sdk.parse_message"
        stack_trace = capture_stack_trace()

        try:
            # Handle different message types
            if isinstance(message, AssistantMessage):
                _handle_assistant_message(message, session_id, api_type, stack_trace)
            elif isinstance(message, UserMessage):
                _handle_user_message(message, session_id)
        except Exception as e:
            logger.error(f"Error in claude_sdk_patch: {e}")

        return message

    message_parser.parse_message = patched_parse_message

    # Also patch local bindings in modules that import parse_message
    # These modules do `from .message_parser import parse_message` which creates local bindings
    try:
        from claude_agent_sdk._internal import client as internal_client

        internal_client.parse_message = patched_parse_message
        logger.debug("Patched _internal.client.parse_message")
    except (ImportError, AttributeError) as e:
        logger.debug(f"Could not patch _internal.client: {e}")

    try:
        from claude_agent_sdk import client as sdk_client

        sdk_client.parse_message = patched_parse_message
        logger.debug("Patched client.parse_message")
    except (ImportError, AttributeError) as e:
        logger.debug(f"Could not patch client: {e}")

    logger.info("claude_agent_sdk patch applied")


def _handle_assistant_message(message, session_id: str, api_type: str, stack_trace: str):
    """Process AssistantMessage: create nodes for tool use blocks."""
    try:
        from claude_agent_sdk.types import ToolUseBlock, TextBlock
    except ImportError:
        return

    model = getattr(message, "model", "unknown")

    # Collect tool use blocks first
    tool_use_blocks = [b for b in message.content if isinstance(b, ToolUseBlock)]

    # If there are tool use blocks, create a "Redacted LLM calls" node first
    redacted_node_id = None
    if tool_use_blocks:
        redacted_node_id = _create_redacted_llm_node(session_id, api_type, stack_trace, model)

    # Process each block
    tool_node_ids = []
    for block in message.content:
        if isinstance(block, ToolUseBlock):
            node_id = _process_tool_use(block, session_id, api_type, stack_trace, redacted_node_id)
            if node_id:
                tool_node_ids.append(node_id)
        elif isinstance(block, TextBlock):
            # Only create nodes for substantial text (final responses, not filler)
            if len(block.text) > 200:
                _process_text_block(block, session_id, api_type, stack_trace, model)

    # Update last tool nodes for next chain
    if tool_node_ids:
        _sdk_last_tool_nodes[session_id] = tool_node_ids


def _handle_user_message(message, session_id: str):
    """Process UserMessage: store tool results for future edge detection."""
    try:
        from claude_agent_sdk.types import ToolResultBlock
    except ImportError:
        return

    content = message.content
    if isinstance(content, list):
        for block in content:
            if isinstance(block, ToolResultBlock):
                _store_tool_result(block, session_id)


def _create_redacted_llm_node(session_id: str, api_type: str, stack_trace: str, model: str) -> str:
    """Create a 'Redacted LLM calls' node representing hidden Claude reasoning."""
    node_id = str(uuid.uuid4())

    # Get the previous tool nodes as sources (the LLM saw their results)
    source_node_ids = _sdk_last_tool_nodes.get(session_id, [])

    input_dict = {
        "type": "redacted_llm",
        "model": model,
        "note": 'Anthropic hides the reasoning steps between tool calls (their "magic").',
    }

    output_obj = {
        "type": "redacted_llm",
        "note": 'Anthropic hides the reasoning steps between tool calls (their "magic").',
    }

    send_graph_node_and_edges(
        node_id=node_id,
        input_dict=input_dict,
        output_obj=output_obj,
        source_node_ids=source_node_ids,
        api_type=api_type,
        stack_trace=stack_trace,
    )

    return node_id


def _process_tool_use(
    block, session_id: str, api_type: str, stack_trace: str, redacted_node_id: str = None
) -> str:
    """Create a node for a tool use block and detect edges."""
    node_id = str(uuid.uuid4())

    # Build input representation
    tool_input_str = json.dumps(block.input, default=str) if block.input else "{}"
    input_dict = {
        "tool_name": block.name,
        "tool_input": block.input,
        "tool_use_id": block.id,
    }

    # Source is the redacted LLM node (the LLM decided to call this tool)
    source_node_ids = [redacted_node_id] if redacted_node_id else []

    # Output is the tool input for now (will be enriched when result comes)
    output_obj = {
        "tool_name": block.name,
        "tool_input": block.input,
    }

    # Send graph node
    send_graph_node_and_edges(
        node_id=node_id,
        input_dict=input_dict,
        output_obj=output_obj,
        source_node_ids=source_node_ids,
        api_type=api_type,
        stack_trace=stack_trace,
    )

    # Store tool input for future matching (content might appear in later calls)
    _store_output_strings(session_id, node_id, tool_input_str)

    # Track tool_use_id -> node_id so we can attach results later
    if session_id not in _sdk_tool_use_to_node:
        _sdk_tool_use_to_node[session_id] = {}
    _sdk_tool_use_to_node[session_id][block.id] = node_id

    return node_id


def _process_text_block(block, session_id: str, api_type: str, stack_trace: str, model: str):
    """Create a node for a substantial text response."""
    node_id = str(uuid.uuid4())

    input_dict = {
        "type": "assistant_response",
        "model": model,
    }

    # Check if any stored outputs appear in this text
    source_node_ids = _find_sources_in_text(session_id, block.text)

    output_obj = {
        "text": block.text[:500] + "..." if len(block.text) > 500 else block.text,
    }

    send_graph_node_and_edges(
        node_id=node_id,
        input_dict=input_dict,
        output_obj=output_obj,
        source_node_ids=source_node_ids,
        api_type=api_type,
        stack_trace=stack_trace,
    )

    # Store text for future matching
    _store_output_strings(session_id, node_id, block.text)


def _store_tool_result(block, session_id: str):
    """Store tool result content for future edge detection."""
    content = block.content
    if not content:
        return

    content_str = content if isinstance(content, str) else json.dumps(content, default=str)

    # Find the node that made this tool call
    tool_use_id = block.tool_use_id
    node_mapping = _sdk_tool_use_to_node.get(session_id, {})
    node_id = node_mapping.get(tool_use_id)

    if node_id:
        # Store the result as output from that node
        _store_output_strings(session_id, node_id, content_str)


def _store_output_strings(session_id: str, node_id: str, text: str):
    """Store output strings for future matching."""
    if session_id not in _sdk_session_outputs:
        _sdk_session_outputs[session_id] = {}

    outputs = _sdk_session_outputs[session_id]
    word_lists = []

    for chunk in split_html_content(text):
        words = tokenize(chunk)
        if words:
            word_lists.append(words)

    if word_lists:
        if node_id in outputs:
            outputs[node_id].extend(word_lists)
        else:
            outputs[node_id] = word_lists


def _find_sources_in_text(session_id: str, text: str) -> List[str]:
    """Find source node IDs whose outputs appear in the given text."""
    input_words = tokenize(text)
    if not input_words:
        return []

    outputs = _sdk_session_outputs.get(session_id, {})
    matches = []

    for node_id, output_word_lists in outputs.items():
        for output_words in output_word_lists:
            is_match, _, _, _ = is_content_match(output_words, input_words)
            if is_match:
                matches.append(node_id)
                break  # Only add node once

    return matches


def clear_sdk_session_data(session_id: str):
    """Clear SDK session data when a session is erased or restarted."""
    if session_id in _sdk_session_outputs:
        del _sdk_session_outputs[session_id]
    if session_id in _sdk_tool_use_to_node:
        del _sdk_tool_use_to_node[session_id]
    if session_id in _sdk_last_tool_nodes:
        del _sdk_last_tool_nodes[session_id]
