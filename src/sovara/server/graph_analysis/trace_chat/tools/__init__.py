"""Tool registry for the ReAct agent loop.

Provides both:
- TOOLS_SCHEMA: OpenAI-format tool definitions for native function calling via litellm
- execute_tool(): dispatch by name to Python functions
"""

from sovara.common.logger import logger as server_logger

from .get_overview import get_overview
from .get_step import get_step
from .verify import verify
from .ask_step import ask_step
from .search import search
from .prompt_edit import (
    list_sections, get_section, edit_section,
    insert_section, delete_section, move_section, undo,
)

# Maps tool name -> Python function
# function signature: f(trace: Trace, ...) -> str
TOOL_FUNCTIONS = {
    "get_overview": get_overview,
    "get_step": get_step,
    "verify": verify,
    "ask_step": ask_step,
    "search": search,
    "list_sections": list_sections,
    "get_section": get_section,
    "edit_section": edit_section,
    "insert_section": insert_section,
    "delete_section": delete_section,
    "move_section": move_section,
    "undo": undo,
}

# OpenAI-format tool schemas for native function calling.
# LiteLLM translates these to each provider's native format.
TOOLS_SCHEMA = [
    {
        "type": "function",
        "function": {
            "name": "get_overview",
            "description": (
                "Returns a high-level overview: step count, conversation structure "
                "(which steps share system prompts and how message history grows), "
                "and per-step metadata (name, message count, output size)."
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
            "name": "get_step",
            "description": (
                "Returns content for a specific step. Use view='diff' to see only "
                "new messages since the last step in the same conversation — much "
                "shorter for later steps."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "step_id": {
                        "type": "integer",
                        "description": "The 1-based index of the step to inspect.",
                    },
                    "view": {
                        "type": "string",
                        "enum": ["full", "diff", "output"],
                        "description": "Level of detail. Default: 'full'.",
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
                "Returns CORRECT/WRONG/UNCERTAIN with explanation. "
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
                "More context-efficient than get_step for targeted questions."
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
                "Searches rendered trace content across input/output fields for a "
                "substring. Returns matching steps, flattened paths, and context snippets."
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
    # -- Section editing tools --
    {
        "type": "function",
        "function": {
            "name": "list_sections",
            "description": (
                "Lists editable input text paths for a step's newly introduced "
                "content. Shared prompts appear only on the step where they are "
                "first introduced. Each entry shows a flattened path, paragraph refs "
                "like body.system::p2, detected role, and preview."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "step_id": {
                        "type": "integer",
                        "description": (
                            "1-based step ID. If omitted and only one prompt exists, "
                            "defaults to the step that introduced it."
                        ),
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_section",
            "description": (
                "Returns one editable path, or one paragraph inside that path. "
                "Use path plus paragraph, or a paragraph ref like body.system::p2."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "step_id": {
                        "type": "integer",
                        "description": "1-based step ID.",
                    },
                    "path": {
                        "type": "string",
                        "description": "Flattened JSON path from list_sections, optionally with a ::pN paragraph suffix.",
                    },
                    "paragraph": {
                        "type": "integer",
                        "description": "Optional 0-based paragraph index within the selected path. Omit when path already includes ::pN.",
                    },
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "edit_section",
            "description": (
                "Rewrites one editable input path, or one paragraph inside that path, "
                "based on a natural-language instruction. Use path plus paragraph, "
                "or a paragraph ref like body.system::p2."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "step_id": {
                        "type": "integer",
                        "description": "1-based step ID.",
                    },
                    "path": {
                        "type": "string",
                        "description": "Flattened JSON path from list_sections, optionally with a ::pN paragraph suffix.",
                    },
                    "paragraph": {
                        "type": "integer",
                        "description": "Optional 0-based paragraph index within the selected path. Omit when path already includes ::pN.",
                    },
                    "instruction": {
                        "type": "string",
                        "description": "What to change (e.g. 'make it more concise', 'add a rule about JSON output').",
                    },
                },
                "required": ["path", "instruction"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "insert_section",
            "description": (
                "Inserts a new paragraph inside one editable path. Use "
                "after_paragraph=-1 to insert at the start. You may also use a "
                "paragraph ref in path to insert after that paragraph."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "step_id": {
                        "type": "integer",
                        "description": "1-based step ID.",
                    },
                    "path": {
                        "type": "string",
                        "description": "Flattened JSON path from list_sections, optionally with a ::pN paragraph suffix.",
                    },
                    "after_paragraph": {
                        "type": "integer",
                        "description": "Insert after this paragraph. -1 = insert at start. Omit when path already includes ::pN.",
                    },
                    "content": {
                        "type": "string",
                        "description": "The text for the new paragraph.",
                    },
                },
                "required": ["path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "delete_section",
            "description": (
                "Removes one paragraph from an editable path. Use paragraph, or a "
                "paragraph ref like body.system::p2."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "step_id": {
                        "type": "integer",
                        "description": "1-based step ID.",
                    },
                    "path": {
                        "type": "string",
                        "description": "Flattened JSON path from list_sections, optionally with a ::pN paragraph suffix.",
                    },
                    "paragraph": {
                        "type": "integer",
                        "description": "0-based paragraph index to delete. Omit when path already includes ::pN.",
                    },
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "move_section",
            "description": (
                "Moves a paragraph to another position within one editable path. "
                "Use from_paragraph, or a paragraph ref like body.system::p2."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "step_id": {
                        "type": "integer",
                        "description": "1-based step ID.",
                    },
                    "path": {
                        "type": "string",
                        "description": "Flattened JSON path from list_sections, optionally with a ::pN paragraph suffix.",
                    },
                    "from_paragraph": {
                        "type": "integer",
                        "description": "Current paragraph index. Omit when path already includes ::pN.",
                    },
                    "to_paragraph": {
                        "type": "integer",
                        "description": "Target paragraph index.",
                    },
                },
                "required": ["path", "to_paragraph"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "undo",
            "description": "Reverts the last edit to a step's sections. Can be called repeatedly.",
            "parameters": {
                "type": "object",
                "properties": {
                    "step_id": {
                        "type": "integer",
                        "description": "1-based step ID.",
                    },
                },
                "required": [],
            },
        },
    },
]


def execute_tool(tool_name: str, trace, params: dict = None) -> str:
    """Look up and execute a tool by name. Returns the result string or an error message."""
    func = TOOL_FUNCTIONS.get(tool_name)
    if func is None:
        available = ", ".join(TOOL_FUNCTIONS.keys())
        return f"Unknown tool: '{tool_name}'. Available tools: {available}"
    params = params or {}
    try:
        return func(trace, **params)
    except Exception as e:
        server_logger.exception("Trace chat tool failed: %s params=%s", tool_name, params)
        return f"Tool '{tool_name}' failed: {e}"
