from dataclasses import dataclass
from enum import Enum
import os
try:
    import readline
except ImportError:
    import pyreadline3 as readline
from typing import Any, Callable
import yaml

from ao.common.logger import logger


@dataclass
class Config:
    python_executable: str = None  # Auto-populated when ao-server runs
    playbook_mode: str = None  # "local" or "cloud"
    playbook_api_key: str = None  # API key for cloud mode

    @classmethod
    def from_yaml_file(cls, yaml_file: str) -> "Config":
        with open(yaml_file, encoding="utf-8") as f:
            config_dict = yaml.safe_load(f)
        known_keys = set(cls.__dataclass_fields__.keys())
        filtered = {k: v for k, v in config_dict.items() if k in known_keys}
        return cls(**filtered)

    def to_yaml_file(self, yaml_file: str) -> None:
        # Create parent directories if they don't exist
        os.makedirs(os.path.dirname(yaml_file), exist_ok=True)
        with open(yaml_file, "w", encoding="utf-8") as f:
            yaml.safe_dump(self.to_dict(), f)
        logger.info(f"Saved config at {yaml_file}")

    def to_dict(self) -> dict:
        result = self.__dict__
        # For serialization, it's best to convert Enums to strings (or their underlying value type).

        def _convert_enums(value):
            if isinstance(value, Enum):
                return value.value
            if isinstance(value, dict):
                if not bool(value):
                    return None
                for key1, value1 in value.items():
                    value[key1] = _convert_enums(value1)
            return value

        for key, value in result.items():
            result[key] = _convert_enums(value)
        result = {k: v for k, v in result.items() if v is not None}
        return result


def complete_path(text, state):
    """Readline completer for filesystem paths."""
    try:
        expanded = os.path.expanduser(text)
        if os.path.isdir(expanded):
            parent = expanded
            prefix = expanded.rstrip(os.sep) + os.sep
        else:
            parent = os.path.dirname(expanded) or "."
            prefix = expanded

        completions = []
        if os.path.isdir(parent):
            for entry in os.listdir(parent):
                candidate = os.path.join(parent, entry)
                if candidate.startswith(prefix) or not text:
                    if text.startswith("~"):
                        home = os.path.expanduser("~")
                        candidate = "~" + candidate[len(home):]
                    if os.path.isdir(candidate):
                        candidate += "/"
                    completions.append(candidate)

        completions.sort()
        if state < len(completions):
            return completions[state]
        return None
    except Exception:
        return None


def _ask_field(
    input_text: str,
    convert_value: Callable[[Any], Any] | None = None,
    default: Any | None = None,
    error_message: str | None = None,
    path_completion: bool = False,
):
    if path_completion:
        readline.set_completer_delims(" \t\n;")
        # libedit (macOS) uses different syntax than GNU readline
        if "libedit" in (readline.__doc__ or ""):
            readline.parse_and_bind("bind ^I rl_complete")
        else:
            readline.parse_and_bind("tab: complete")
        readline.set_completer(complete_path)
    else:
        readline.set_completer(None)
    ask_again = True
    while ask_again:
        result = input(input_text)
        try:
            if default is not None and len(result) == 0:
                return default
            return convert_value(result) if convert_value is not None else result
        except Exception:
            if error_message is not None:
                print(error_message)


def _convert_yes_no_to_bool(value: str) -> bool:
    return {"yes": True, "no": False}[value.lower()]


def _convert_to_valid_path(value: str) -> str:
    value = os.path.abspath(value)
    if os.path.isdir(value):
        return value
    raise ValueError("Invalid path.")
