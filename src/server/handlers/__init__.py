"""Message handlers for the server, split by source."""

from ao.server.handlers.handler_utils import logger

from ao.server.handlers.ui_handlers import (
    handle_edit_input,
    handle_edit_output,
    handle_update_node,
    handle_update_run_name,
    handle_update_result,
    handle_update_notes,
    handle_erase,
)

from ao.server.handlers.runner_handlers import (
    handle_add_node,
    handle_deregister_message,
    handle_update_command,
    handle_log,
)

__all__ = [
    "logger",
    # UI handlers
    "handle_edit_input",
    "handle_edit_output",
    "handle_update_node",
    "handle_update_run_name",
    "handle_update_result",
    "handle_update_notes",
    "handle_erase",
    # Runner handlers
    "handle_add_node",
    "handle_deregister_message",
    "handle_update_command",
    "handle_log",
]
