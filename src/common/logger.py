import logging


def setup_logging():
    # Clear out any old handlers (especially in REPL or interactive walks)
    root = logging.getLogger("AO")
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


def create_file_logger(log_file: str) -> logging.Logger:
    """
    Create a logger with file handler for server components.

    Args:
        log_file: Path to the log file

    Returns:
        Configured logger instance
    """
    file_logger = logging.getLogger(log_file)

    # Avoid adding duplicate handlers
    if file_logger.handlers:
        return file_logger

    file_logger.setLevel(logging.DEBUG)  # NOTE: This is server logs, can stay DEBUG
    file_logger.propagate = False  # Don't propagate to root logger

    # File handler
    file_handler = logging.FileHandler(log_file)
    file_handler.setLevel(logging.DEBUG)

    # Formatter
    formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
    file_handler.setFormatter(formatter)

    file_logger.addHandler(file_handler)
    return file_logger


logger = setup_logging()
