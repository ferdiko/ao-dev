from dataclasses import dataclass
from enum import Enum
import os
from pathlib import Path

try:
    import readline
except ImportError:
    import pyreadline3 as readline
from typing import Any, Callable, Optional, Union
import yaml

from ao.common.logger import logger


@dataclass
class Config:
    project_root: str
    database_url: str = None
    python_executable: str = None  # Auto-populated when ao-server runs
    playbook_mode: str = None  # "local" or "cloud"
    playbook_api_key: str = None  # API key for cloud mode

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


# ==============================================================================
# We try to derive the project root relative to the user working directory.
# All of the below is implementing this heuristic search.
# ==============================================================================
def derive_project_root() -> str:
    """
    Walk upward from current working directory to infer a Python project root.

    Heuristics (in order of strength):
      0) If folders of our repo are found in the path, use to make our example_workflows the repo root.
      1) If the directory contains project/repo markers (pyproject.toml, .git, etc.), STOP and return it.
      2) If a parent directory name cannot be part of a Python module path (not an identifier), STOP at that directory.
      3) If we encounter common non-project anchor dirs (~/Documents, ~/Downloads, /usr, C:\\Windows, /Applications, etc.),
         DO NOT go above them; return the last "good" directory below.
      4) If we detect we're about to cross a virtualenv boundary, return the last good directory below.
      5) If we hit the filesystem root without any better signal, return the last good directory we saw.

    "Last good directory" = the most recent directory we visited that could plausibly be part of an importable path
    (i.e., its name is a valid identifier or it's a top-level candidate that doesn't obviously look like an anchor).

    Returns:
        String path to the inferred project root.
    """
    start = os.getcwd()
    cur = _normalize_start(start)
    last_good = cur

    for p in _walk_up(cur):
        # Highest priority: if this is the ao repo itself, use example_workflows subdirectory
        # to avoid AST-rewriting the ao source code (which causes import issues)
        if p.name in ("agent-copilot", "agent-dev", "ao-agent-dev"):
            return str(p / "example_workflows")

        # Strong signal: repo/project markers at this directory
        if _has_project_markers(p) or _has_src_layout_hint(p):
            return str(p)

        # If this segment cannot be in a Python dotted path, don't go above it.
        if not _segment_is_import_safe(p):
            return str(p)

        # If this is a known "anchor" (Documents, Downloads, Program Files, /usr, etc.),
        # don't float above it; the project likely lives below.
        if _is_common_non_project_dir(p):
            return str(last_good)

        # Don't float above a virtualenv boundary (if start happened to be inside one).
        if _looks_like_virtualenv_root(p):
            return str(last_good)

        # If nothing special, this remains a reasonable candidate.
        last_good = p

    # We reached the OS root without a decisive marker.
    return str(last_good)


def _normalize_start(start: Optional[Union[str, os.PathLike]]) -> Path:
    if start is None:
        start = Path.cwd()
    p = Path(start)
    if p.is_file():
        p = p.parent
    return p.resolve()


def _walk_up(start_dir: Path):
    """Yield start_dir, then its parents up to the filesystem root."""
    p = start_dir
    while True:
        yield p
        if p.parent == p:
            break  # reached filesystem root
        p = p.parent


def _has_project_markers(p: Path) -> bool:
    """
    Things that strongly indicate "this is a project/repo root".
    You can extend this list to fit your org/monorepo conventions.
    """
    files = {
        "pyproject.toml",
        "poetry.lock",
        "Pipfile",
        "requirements.txt",
        "setup.cfg",
        "setup.py",
        "tox.ini",
        ".editorconfig",
        ".flake8",
        "mypy.ini",
        "README.md",
        "README.rst",
    }
    dirs = {
        ".git",
        ".hg",
        ".svn",
        ".idea",  # JetBrains project
        ".vscode",  # VS Code project
    }
    return any((p / f).exists() for f in files) or any((p / d).is_dir() for d in dirs)


def _has_src_layout_hint(p: Path) -> bool:
    """
    Mild positive signal: a 'src/' directory that appears to contain importable packages.
    We don't require __init__.py (PEP 420 namespaces exist). We only treat this as a hint,
    not as strong as explicit markers—so it's folded into `_has_project_markers`-like logic.
    """
    src = p / "src"
    if not src.is_dir():
        return False

    # Does src contain at least one directory that looks like a Python package segment?
    for child in src.iterdir():
        if child.is_dir() and _name_looks_like_package(child.name):
            return True
    return False


def _segment_is_import_safe(p: Path) -> bool:
    """
    A directory name that cannot be a valid Python identifier cannot be part of a dotted module path.
    If it's not import-safe, we don't go above it (we stop at it).
    """
    name = p.name
    # At filesystem root, name may be '' (POSIX) or 'C:\\' (Windows); treat as non-import-segment.
    if name == "" or p.parent == p:
        return False
    return name.isidentifier()


def _name_looks_like_package(name: str) -> bool:
    """
    Heuristic for a directory that *could* be an importable package:
    - valid identifier (letters, digits, underscore; not starting with digit)
    """
    return name.isidentifier()


def _looks_like_virtualenv_root(p: Path) -> bool:
    """
    Common virtualenv layouts:
      - <venv>/bin/activate      (POSIX)
      - <venv>/Scripts/activate  (Windows)
    Also many people name the dir 'venv', '.venv', 'env', '.env'
    """
    if p.name in {"venv", ".venv", "env", ".env"}:
        return True
    if (p / "bin" / "activate").is_file():
        return True
    if (p / "Scripts" / "activate").is_file():
        return True
    return False


def _is_common_non_project_dir(p: Path) -> bool:
    """
    Directories that are very often "anchors" above real projects.
    We avoid floating above these; instead we return the last good dir below them.
    This is conservative and OS-aware.
    """
    # Normalize case on Windows to avoid case-sensitivity surprises.
    name_lower = p.name.lower()

    home = Path.home()
    try:
        in_home = home in p.parents or p == home
    except Exception:
        in_home = False

    # --- macOS / Linux-ish anchors ---
    posix_anchors = {
        "applications",  # macOS
        "library",  # macOS / shared
        "system",  # macOS
        "usr",
        "bin",
        "sbin",
        "etc",
        "var",
        "opt",
        "proc",
        "dev",
    }
    posix_home_anchors = {
        "documents",
        "downloads",
        "desktop",
        "music",
        "movies",
        "pictures",
        "public",
        "library",  # user's Library on macOS
    }

    # --- Windows anchors ---
    windows_anchors = {
        "windows",
        "program files",
        "program files (x86)",
        "programdata",
        "intel",
        "nvidia corporation",
    }
    windows_home_anchors = {
        "documents",
        "downloads",
        "desktop",
        "pictures",
        "music",
        "videos",
        "onedrive",
        "dropbox",
    }

    # Filesystem root? Treat as an anchor we don't climb past.
    if p.parent == p:
        return True

    if os.name == "nt":
        if name_lower in windows_anchors:
            return True
        if in_home and name_lower in windows_home_anchors:
            return True
        # Example: C:\Users\<me>\Documents — stop at Documents
        if in_home and name_lower == "users":
            return True
    else:
        if name_lower in posix_anchors:
            return True
        if in_home and name_lower in posix_home_anchors:
            return True

    # Generic cloud-sync / archive / tooling anchors (cross-platform):
    generic_anchors = {
        "icloud drive",
        "google drive",
        "dropbox",
        "box",
        "library",  # often a user-level anchor on macOS
        "applications",  # second chance
    }
    if name_lower in generic_anchors:
        return True

    return False
