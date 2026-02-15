from dataclasses import dataclass
from enum import Enum
import os
from pathlib import Path

try:
    import readline
except ImportError:
    import pyreadline3 as readline
from typing import Any, Callable
import yaml

from ao.common.logger import logger


@dataclass
class Config:
    database_url: str = None
    python_executable: str = None  # Auto-populated when ao-server runs

    @classmethod
    def from_yaml_file(cls, yaml_file: str) -> "Config":
        with open(yaml_file, encoding="utf-8") as f:
            config_dict = yaml.safe_load(f)
        # maybe here we need to do some processing if we have more involved types
        extra_keys = sorted(set(config_dict.keys()) - set(cls.__dataclass_fields__.keys()))
        if len(extra_keys) > 0:
            raise ValueError(f"The config file at {yaml_file} had unknown keys ({extra_keys}).")
        return cls(**config_dict)

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
    incomplete_path = Path(text)
    if incomplete_path.is_dir():
        completions = [p.as_posix() for p in incomplete_path.iterdir()]
    elif incomplete_path.exists():
        completions = [incomplete_path]
    else:
        exists_parts = Path(".")
        for part in incomplete_path.parts:
            test_next_part = exists_parts / part
            if test_next_part.exists():
                exists_parts = test_next_part

        completions = []
        for p in exists_parts.iterdir():
            p_str = p.as_posix()
            if p_str.startswith(text):
                completions.append(p_str)
    return completions[state]


def _ask_field(
    input_text: str,
    convert_value: Callable[[Any], Any] | None = None,
    default: Any | None = None,
    error_message: str | None = None,
):
    # we want to treat '/' as part of a word, so override the delimiters
    readline.set_completer_delims(" \t\n;")
    readline.parse_and_bind("tab: complete")
    readline.set_completer(complete_path)
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
