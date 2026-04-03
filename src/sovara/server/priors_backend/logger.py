"""Logging for priors storage and retrieval."""

import logging

from sovara.common.constants import PRIORS_SERVER_LOG
from sovara.common.logger import create_file_logger, logger as root_logger

server_logger = create_file_logger(PRIORS_SERVER_LOG, level=logging.WARNING)
logger = server_logger
console_logger = root_logger
