import logging
import os
from pathlib import Path


def setup_logging():
    # Clear out any old handlers (especially in REPL or interactive walks)
    root = logging.getLogger("Sovara")
    if root.handlers:
        root.handlers.clear()

    root.setLevel(logging.DEBUG)  # NOTE: Set to CRITICAL in releases (prints to terminal)

    # Create a console handler
    handler = logging.StreamHandler()

    # Create and set a formatter
    formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    handler.setFormatter(formatter)

    # Add handler to logger
    root.addHandler(handler)
    return root


_FILE_FORMATTER = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")


def create_file_logger(
    log_file: str,
    *,
    logger_name: str | None = None,
    level: int = logging.DEBUG,
    replace_handlers: bool = False,
    formatter: logging.Formatter | None = None,
) -> logging.Logger:
    """
    Create or configure a file-backed logger for server components.

    Args:
        log_file: Path to the log file
        logger_name: Logger name to configure. Defaults to the log file path.
        level: Logging level for the logger and file handler.
        replace_handlers: Whether to replace existing handlers on that logger.
        formatter: Optional formatter override for the file handler.

    Returns:
        Configured logger instance
    """
    file_logger = logging.getLogger(logger_name or log_file)
    resolved = str(Path(log_file).expanduser().resolve())

    if file_logger.handlers and not replace_handlers:
        return file_logger

    if replace_handlers:
        for handler in list(file_logger.handlers):
            file_logger.removeHandler(handler)
            try:
                handler.close()
            except Exception:
                pass

    file_logger.setLevel(level)
    file_logger.propagate = False

    os.makedirs(os.path.dirname(resolved), exist_ok=True)
    file_handler = logging.FileHandler(resolved, mode="a")
    file_handler.setLevel(level)
    file_handler.setFormatter(formatter or _FILE_FORMATTER)

    file_logger.addHandler(file_handler)
    return file_logger


logger = setup_logging()
