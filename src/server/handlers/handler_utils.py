"""Shared utilities for message handlers."""

from ao.common.logger import create_file_logger
from ao.common.constants import MAIN_SERVER_LOG

logger = create_file_logger(MAIN_SERVER_LOG)
