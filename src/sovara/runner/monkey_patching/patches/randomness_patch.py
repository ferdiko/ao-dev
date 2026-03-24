import os
import random
import warnings
from sovara.common.logger import logger


def uuid_patch():
    """Patch uuid4 to use random.getrandbits for reproducible UUIDs."""
    import uuid
    from uuid import UUID

    def uuid4():
        return UUID(int=random.getrandbits(128), version=4)

    uuid.uuid4 = uuid4


def numpy_seed_patch():
    """Seed numpy's RNG with SOVARA_SEED when numpy is imported."""
    try:
        from numpy.random import seed
    except ImportError:
        logger.info("numpy not installed, skipping numpy seed patch")
        return

    ao_seed = os.environ.get("SOVARA_SEED")
    if ao_seed:
        with warnings.catch_warnings():
            warnings.filterwarnings("ignore", module="numpy")
            seed(int(ao_seed))


def torch_seed_patch():
    """Seed torch's RNG with SOVARA_SEED when torch is imported."""
    try:
        from torch import manual_seed
    except ImportError:
        logger.info("torch not installed, skipping torch seed patch")
        return

    ao_seed = os.environ.get("SOVARA_SEED")
    if ao_seed:
        with warnings.catch_warnings():
            warnings.filterwarnings("ignore", module="torch")
            manual_seed(int(ao_seed))


def random_seed_patch():
    """Seed Python's random module with SOVARA_SEED."""
    ao_seed = os.environ.get("SOVARA_SEED")
    if ao_seed:
        random.seed(int(ao_seed))
