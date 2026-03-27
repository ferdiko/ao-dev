"""Tool registry for the ReAct agent loop.

Provides both:
- TOOLS_SCHEMA: OpenAI-format tool definitions for native function calling via litellm
- execute_tool(): dispatch by name to Python functions
"""

from .get_overview import get_overview
from .get_step import get_step
from .verify import verify
from .ask_step import ask_step
from .search import search
from .prompt_edit import (
    list_sections, get_section, edit_section, bulk_edit,
    insert_section, delete_section, move_section, undo,
)

# Maps tool name -> Python function
# function signature: f(trace: Trace, **params) -> str
TOOL_FUNCTIONS = {
    "get_overview": get_overview,
    "get_step": get_step,
    "verify": verify,
    "ask_step": ask_step,
    "search": search,
    "list_sections": list_sections,
    "get_section": get_section,
    "edit_section": edit_section,
    "bulk_edit": bulk_edit,
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
                "and per-step metadata (model/tool, message count, output size)."
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
                "Searches trace content (system prompts, inputs, outputs) for a "
                "substring. Returns matching steps with context snippets."
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
                "Lists editable sections for a step's new content — system prompt "
                "(if first introduced in this step) and new messages. Each section "
                "shows its role ([system], [user], [assistant]), label, and preview."
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
            "description": "Returns the full text of one section by index.",
            "parameters": {
                "type": "object",
                "properties": {
                    "step_id": {
                        "type": "integer",
                        "description": "1-based step ID.",
                    },
                    "index": {
                        "type": "integer",
                        "description": "0-based section index (from list_sections).",
                    },
                },
                "required": ["index"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "edit_section",
            "description": (
                "Rewrites one section based on a natural-language instruction. "
                "Works on any section — system prompt, user input, or assistant output."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "step_id": {
                        "type": "integer",
                        "description": "1-based step ID.",
                    },
                    "index": {
                        "type": "integer",
                        "description": "0-based section index to edit.",
                    },
                    "instruction": {
                        "type": "string",
                        "description": "What to change (e.g. 'make it more concise', 'add a rule about JSON output').",
                    },
                },
                "required": ["index", "instruction"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "bulk_edit",
            "description": (
                "Applies the same editing instruction to every section in parallel. "
                "Use for style changes or global rules."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "step_id": {
                        "type": "integer",
                        "description": "1-based step ID.",
                    },
                    "instruction": {
                        "type": "string",
                        "description": "What to change across all sections.",
                    },
                },
                "required": ["instruction"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "insert_section",
            "description": "Inserts a new section after the given index. Use after_index=-1 to insert at the start.",
            "parameters": {
                "type": "object",
                "properties": {
                    "step_id": {
                        "type": "integer",
                        "description": "1-based step ID.",
                    },
                    "after_index": {
                        "type": "integer",
                        "description": "Insert after this index. -1 = insert at start.",
                    },
                    "content": {
                        "type": "string",
                        "description": "The text for the new section.",
                    },
                },
                "required": ["after_index", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "delete_section",
            "description": "Removes a section by index.",
            "parameters": {
                "type": "object",
                "properties": {
                    "step_id": {
                        "type": "integer",
                        "description": "1-based step ID.",
                    },
                    "index": {
                        "type": "integer",
                        "description": "0-based section index to delete.",
                    },
                },
                "required": ["index"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "move_section",
            "description": "Moves a section from one index to another.",
            "parameters": {
                "type": "object",
                "properties": {
                    "step_id": {
                        "type": "integer",
                        "description": "1-based step ID.",
                    },
                    "from_index": {
                        "type": "integer",
                        "description": "Current index of the section to move.",
                    },
                    "to_index": {
                        "type": "integer",
                        "description": "Target index for the section.",
                    },
                },
                "required": ["from_index", "to_index"],
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
        return f"Tool '{tool_name}' failed: {e}"
