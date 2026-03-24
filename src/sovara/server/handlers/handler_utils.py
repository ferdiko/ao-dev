"""Shared utilities for message handlers."""

from sovara.common.logger import create_file_logger
from sovara.common.constants import MAIN_SERVER_LOG

logger = create_file_logger(MAIN_SERVER_LOG)
