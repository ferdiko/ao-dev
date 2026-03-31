"""Shared cancellation helpers for trace chat requests."""

from __future__ import annotations

import threading


class TraceChatCancelled(Exception):
    """Raised when an in-flight trace chat request is cancelled."""


def raise_if_cancelled(cancel_event: threading.Event | None) -> None:
    if cancel_event is not None and cancel_event.is_set():
        raise TraceChatCancelled("Trace chat canceled")
