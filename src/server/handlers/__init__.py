"""Message handlers for the main server, split by source."""

from ao.server.handlers.handler_utils import send_json, logger

from ao.server.handlers.ui_handlers import (
    handle_restart_message,
    handle_edit_input,
    handle_edit_output,
    handle_update_node,
    handle_update_run_name,
    handle_update_result,
    handle_update_notes,
    handle_get_graph,
    handle_erase,
    handle_get_all_experiments,
    handle_get_more_experiments,
    handle_get_experiment_detail,
    handle_get_lessons_applied,
)

from ao.server.handlers.runner_handlers import (
    handle_add_node,
    handle_add_subrun,
    handle_deregister_message,
    handle_update_command,
    handle_log,
)

__all__ = [
    # Utils
    "send_json",
    "logger",
    # UI handlers
    "handle_restart_message",
    "handle_edit_input",
    "handle_edit_output",
    "handle_update_node",
    "handle_update_run_name",
    "handle_update_result",
    "handle_update_notes",
    "handle_get_graph",
    "handle_erase",
    "handle_get_all_experiments",
    "handle_get_more_experiments",
    "handle_get_experiment_detail",
    "handle_get_lessons_applied",
    # Runner handlers
    "handle_add_node",
    "handle_add_subrun",
    "handle_deregister_message",
    "handle_update_command",
    "handle_log",
]
