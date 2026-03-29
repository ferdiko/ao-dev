"""Helpers for reading and updating text-like leaves inside nested `to_show` JSON."""

from typing import Any


def _split_json_path(path: str) -> list[str]:
    if not path:
        return []
    return path.split(".")


def _consume_dict_key(current: dict, parts: list[str], path: str, *, allow_missing: bool = False) -> tuple[str, int]:
    """Resolve one dict hop, supporting flattened dotted keys like `body.messages`."""
    for consumed in range(len(parts), 0, -1):
        key = ".".join(parts[:consumed])
        if key in current:
            return key, consumed

    if allow_missing and parts:
        return parts[0], 1

    raise KeyError(path)


def _get_json_path(value: Any, path: str) -> Any:
    current = value
    parts = _split_json_path(path)
    idx = 0
    while idx < len(parts):
        part = parts[idx]
        if isinstance(current, list):
            current = current[int(part)]
        elif isinstance(current, dict):
            key, consumed = _consume_dict_key(current, parts[idx:], path)
            current = current[key]
            idx += consumed
            continue
        else:
            raise KeyError(path)
        idx += 1
    return current


def _set_json_path(value: Any, path: str, new_value: Any) -> Any:
    parts = _split_json_path(path)
    if not parts:
        return new_value

    def _set(current: Any, remaining: list[str]) -> Any:
        if not remaining:
            return new_value

        if isinstance(current, list):
            index = int(remaining[0])
            current[index] = _set(current[index], remaining[1:])
            return current

        if isinstance(current, dict):
            exact_key = ".".join(remaining)
            if exact_key in current:
                current[exact_key] = new_value
                return current

            for consumed in range(len(remaining) - 1, 0, -1):
                key = ".".join(remaining[:consumed])
                if key in current:
                    current[key] = _set(current[key], remaining[consumed:])
                    return current

            key, consumed = _consume_dict_key(current, remaining, path, allow_missing=True)
            if consumed == len(remaining):
                current[key] = new_value
                return current

            next_part = remaining[consumed]
            if key not in current or not isinstance(current[key], (dict, list)):
                current[key] = [] if next_part.isdigit() else {}
            current[key] = _set(current[key], remaining[consumed:])
            return current

        raise KeyError(path)

    return _set(value, parts)


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
