"""Helpers for reading and updating text-like leaves inside nested `to_show` JSON."""

from typing import Any


def _split_json_path(path: str) -> list[str]:
    if not path:
        return []
    return path.split(".")


def _get_json_path(value: Any, path: str) -> Any:
    current = value
    for part in _split_json_path(path):
        if isinstance(current, list):
            current = current[int(part)]
        elif isinstance(current, dict):
            current = current[part]
        else:
            raise KeyError(path)
    return current


def _set_json_path(value: Any, path: str, new_value: Any) -> Any:
    parts = _split_json_path(path)
    if not parts:
        return new_value

    current = value
    for idx, part in enumerate(parts[:-1]):
        next_part = parts[idx + 1]
        if isinstance(current, list):
            current = current[int(part)]
        elif isinstance(current, dict):
            if part not in current:
                current[part] = [] if next_part.isdigit() else {}
            current = current[part]
        else:
            raise KeyError(path)

    last = parts[-1]
    if isinstance(current, list):
        current[int(last)] = new_value
    elif isinstance(current, dict):
        current[last] = new_value
    else:
        raise KeyError(path)
    return value


def set_text_value(to_show: dict, path: str, codec: str, new_text: str, *, strict: bool = False) -> bool:
    """Replace a text leaf by path while preserving the current container shape."""
    try:
        current = _get_json_path(to_show, path)
    except Exception:
        if strict:
            raise
        return False

    if codec == "text_block_list" and isinstance(current, list):
        updated = []
        inserted = False
        for block in current:
            if isinstance(block, dict) and block.get("type") == "text":
                if not inserted:
                    updated.append({**block, "text": new_text})
                    inserted = True
                continue
            updated.append(block)
        if not inserted:
            updated.append({"type": "text", "text": new_text})
        _set_json_path(to_show, path, updated)
        return True

    _set_json_path(to_show, path, new_text)
    return True
