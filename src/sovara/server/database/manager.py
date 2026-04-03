import threading
from collections import defaultdict

from ._shared import BadRequestError, ResourceNotFoundError
from .llm_calls import LlmCallsMixin
from .priors import PriorsMixin
from .projects import ProjectsMixin
from .runs import RunsMixin
from .users import UsersMixin


class DatabaseManager(UsersMixin, ProjectsMixin, RunsMixin, LlmCallsMixin, PriorsMixin):
    """Manages database operations using a pluggable backend."""

    def __init__(self):
        from sovara.common.constants import ATTACHMENT_CACHE

        self.cache_attachments = True
        self.attachment_cache_dir = ATTACHMENT_CACHE
        self._occurrence_counters: dict[tuple[str, str], int] = defaultdict(int)
        self._occurrence_lock = threading.Lock()

    @property
    def user_id(self):
        from sovara.common.user import read_user_id

        return read_user_id()

    @property
    def backend(self):
        if not hasattr(self, "_backend_module"):
            from sovara.server.database import sqlite

            self._backend_module = sqlite
        return self._backend_module

    def query_one(self, query, params=None):
        return self.backend.query_one(query, params or ())

    def query_all(self, query, params=None):
        return self.backend.query_all(query, params or ())

    def execute(self, query, params=None):
        return self.backend.execute(query, params or ())

    def clear_connections(self) -> None:
        clear = getattr(self.backend, "clear_connections", None)
        if callable(clear):
            clear()


DB = DatabaseManager()
