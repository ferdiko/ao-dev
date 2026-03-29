"""Constants for the in-repo priors backend."""

import os

from sovara.common.constants import SOVARA_HOME

PRIORS_BACKEND_HOME = os.path.join(SOVARA_HOME, "priors")
os.makedirs(PRIORS_BACKEND_HOME, exist_ok=True)

SCOPE_METADATA_FILENAME = ".scope.json"
RETRIEVAL_ALGORITHM_VERSION = "folder-llm-v1"
