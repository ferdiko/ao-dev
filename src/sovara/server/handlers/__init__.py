"""Message handlers for the server, split by source."""

from sovara.server.handlers.handler_utils import logger

from sovara.server.handlers.ui_handlers import (
    handle_edit_input,
    handle_edit_output,
    handle_update_node,
    handle_update_run_name,
    handle_update_thumb_label,
    handle_update_notes,
    handle_erase,
)

from sovara.server.handlers.runner_handlers import (
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
    "handle_update_thumb_label",
    "handle_update_notes",
    "handle_erase",
    # Runner handlers
    "handle_add_node",
    "handle_deregister_message",
    "handle_update_command",
    "handle_log",
]
