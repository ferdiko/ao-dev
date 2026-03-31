"""Tool registry for the ReAct agent loop.

Provides both:
- TOOLS_SCHEMA: OpenAI-format tool definitions for native function calling via litellm
- execute_tool(): dispatch by name to Python functions
"""

import inspect

from ..cancel import TraceChatCancelled
from ..logger import get_logger

server_logger = get_logger()

from .get_trace_overview import get_trace_overview
from .get_step_snapshot import get_step_snapshot
from .get_step_overview import get_step_overview
from .verify import verify
from .ask_step import ask_step
from .search import search
from .edit_content import (
    delete_content_unit,
    edit_content,
    get_content_unit,
    undo,
)

# Maps tool name -> Python function
# function signature: f(trace: Trace, ...) -> str
TOOL_FUNCTIONS = {
    "get_trace_overview": get_trace_overview,
    "get_step_snapshot": get_step_snapshot,
    "get_step_overview": get_step_overview,
    "verify": verify,
    "ask_step": ask_step,
    "search": search,
    "get_content_unit": get_content_unit,
    "edit_content": edit_content,
    "delete_content_unit": delete_content_unit,
    "undo": undo,
}

# OpenAI-format tool schemas for native function calling.
# LiteLLM translates these to each provider's native format.
TOOLS_SCHEMA = [
    {
        "type": "function",
        "function": {
            "name": "get_trace_overview",
            "description": (
                "Returns a high-level overview of the trace: step count, conversation structure, "
                "and per-step metadata."
            ),
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_step_snapshot",
            "description": (
                "Returns a raw snapshot of one step. scope='full' returns full input "
                "and output. scope='new_input' returns only new input plus full output. "
                "Large requests may return a compact preview instead of raw content."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "step_id": {
                        "type": "integer",
                        "description": "The 1-based index of the step to inspect.",
                    },
                    "scope": {
                        "type": "string",
                        "enum": ["full", "new_input"],
                        "description": "Which slice of the step to load. Default: 'full'.",
                    },
                },
                "required": ["step_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_step_overview",
            "description": (
                "Best first look at a step: returns the cached step summary when available "
                "plus visible input and output content units with step-global content_id handles. "
                "Longer content is summarized and can be expanded with get_content_unit."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "step_id": {
                        "type": "integer",
                        "description": "The 1-based index of the step to inspect.",
                    },
                },
                "required": ["step_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "verify",
            "description": (
                "Checks whether a step's output is correct given its instructions. "
                "Returns a plain-language judgment saying the step looks correct, wrong, uncertain, "
                "or was not evaluated when the verifier response is malformed. "
                "If step_id is omitted, verifies ALL steps (may be slow)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "step_id": {
                        "type": "integer",
                        "description": "The 1-based index of the step to verify. Omit to verify all.",
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "ask_step",
            "description": (
                "Asks a specific question about a step and returns only the answer. "
                "Prefer this over get_step_snapshot for targeted questions."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "step_id": {
                        "type": "integer",
                        "description": "The 1-based index of the step.",
                    },
                    "question": {
                        "type": "string",
                        "description": "The question to answer about this step.",
                    },
                },
                "required": ["step_id", "question"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search",
            "description": (
                "Searches rendered trace content for a substring. Returns matching steps, "
                "locations, and context snippets."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "The substring to search for (case-insensitive).",
                    },
                },
                "required": ["query"],
            },
        },
    },
    # -- Content editing tools --
    {
        "type": "function",
        "function": {
            "name": "get_content_unit",
            "description": (
                "Returns one content unit from get_step_overview for a specific step by content_id."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "step_id": {
                        "type": "integer",
                        "description": "1-based step ID.",
                    },
                    "content_id": {
                        "type": "string",
                        "description": "Content handle from get_step_overview, like c0 or c1.",
                    },
                },
                "required": ["step_id", "content_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "edit_content",
            "description": (
                "Rewrites one editable content unit from get_step_overview for a specific step by content_id."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "step_id": {
                        "type": "integer",
                        "description": "1-based step ID.",
                    },
                    "content_id": {
                        "type": "string",
                        "description": "Content handle from get_step_overview, like c0 or c1.",
                    },
                    "instruction": {
                        "type": "string",
                        "description": "What to change (e.g. 'make it more concise', 'add a rule about JSON output').",
                    },
                },
                "required": ["step_id", "content_id", "instruction"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "delete_content_unit",
            "description": (
                "Removes one content unit for a specific step identified by content_id from "
                "get_step_overview."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "step_id": {
                        "type": "integer",
                        "description": "1-based step ID.",
                    },
                    "content_id": {
                        "type": "string",
                        "description": "Content handle from get_step_overview.",
                    },
                },
                "required": ["step_id", "content_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "undo",
            "description": "Reverts the last edit to a step. Can be called repeatedly.",
            "parameters": {
                "type": "object",
                "properties": {
                    "step_id": {
                        "type": "integer",
                        "description": "1-based step ID.",
                    },
                },
                "required": ["step_id"],
            },
        },
    },
]


def execute_tool(
    tool_name: str,
    trace,
    params: dict = None,
    *,
    log_tag: str = "",
    cancel_event=None,
) -> str:
    """Look up and execute a tool by name. Returns the result string or an error message."""
    func = TOOL_FUNCTIONS.get(tool_name)
    if func is None:
        available = ", ".join(TOOL_FUNCTIONS.keys())
        return f"Unknown tool: '{tool_name}'. Available tools: {available}"
    params = params or {}
    try:
        signature = inspect.signature(func)
        if cancel_event is not None and "cancel_event" in signature.parameters:
            return func(trace, cancel_event=cancel_event, **params)
        return func(trace, **params)
    except TraceChatCancelled:
        raise
    except Exception as e:
        if log_tag:
            server_logger.exception("%s Trace chat tool failed: %s params=%s", log_tag, tool_name, params)
        else:
            server_logger.exception("Trace chat tool failed: %s params=%s", tool_name, params)
        return f"Tool '{tool_name}' failed: {e}"
