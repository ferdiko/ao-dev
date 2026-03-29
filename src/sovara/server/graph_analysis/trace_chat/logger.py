import logging
import os
from pathlib import Path

from sovara.common.constants import INFERENCE_SERVER_LOG

LOGGER_NAME = "sovara_agent"
DEFAULT_STANDALONE_LOG = "agent.log"
_FORMATTER = logging.Formatter(
    "%(asctime)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)


def get_logger() -> logging.Logger:
    return logging.getLogger(LOGGER_NAME)


def format_log_tags(scope: str, **fields) -> str:
    parts = [scope]
    for key, value in fields.items():
        if value is None:
            continue
        text = " ".join(str(value).split()).strip()
        if not text:
            continue
        parts.append(f"{key}={text.replace(' ', '_')}")
    return "[" + " ".join(parts) + "]"


def configure_logger(log_file: str, *, level: int = logging.INFO) -> logging.Logger:
    logger = get_logger()
    resolved = str(Path(log_file).expanduser().resolve())

    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        try:
            handler.close()
        except Exception:
            pass

    os.makedirs(os.path.dirname(resolved), exist_ok=True)
    file_handler = logging.FileHandler(resolved, mode="a")
    file_handler.setLevel(level)
    file_handler.setFormatter(_FORMATTER)

    logger.setLevel(level)
    logger.propagate = False
    logger.addHandler(file_handler)
    return logger


def ensure_standalone_logger() -> logging.Logger:
    logger = get_logger()
    if logger.handlers:
        return logger
    return configure_logger(DEFAULT_STANDALONE_LOG, level=logging.INFO)


def configure_inference_process_logging() -> logging.Logger:
    root_logger = logging.getLogger("Sovara")
    root_logger.setLevel(logging.WARNING)
    for handler in root_logger.handlers:
        handler.setLevel(logging.WARNING)

    return configure_logger(INFERENCE_SERVER_LOG, level=logging.INFO)
