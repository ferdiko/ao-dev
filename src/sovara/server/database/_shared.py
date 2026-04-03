from dataclasses import dataclass
from typing import Any, Optional


class ResourceNotFoundError(LookupError):
    """Raised when a request references a missing DB-backed resource."""


class BadRequestError(ValueError):
    """Raised when a request payload cannot be applied safely."""


@dataclass
class CacheOutput:
    """Encapsulates the output of cache operations for LLM calls."""

    input_dict: dict
    output: Optional[Any]
    node_uuid: Optional[str]
    input_pickle: bytes
    input_hash: str
    run_id: str
    stack_trace: Optional[str] = None
