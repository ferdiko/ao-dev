"""Persisted retrieval cache for priors retrieval requests."""

from __future__ import annotations

import json
import os
import sqlite3
import threading
from typing import Any

from sovara.common.constants import SOVARA_HOME
from sovara.common.utils import hash_input

_CACHE_DIR = os.path.join(SOVARA_HOME, "priors")
_CACHE_PATH = os.path.join(_CACHE_DIR, "retrieval-cache.sqlite")
_INIT_LOCK = threading.Lock()
_INITIALIZED = False


def _ensure_db() -> None:
    global _INITIALIZED
    if _INITIALIZED:
        return
    with _INIT_LOCK:
        if _INITIALIZED:
            return
        os.makedirs(_CACHE_DIR, exist_ok=True)
        conn = sqlite3.connect(_CACHE_PATH, timeout=30.0)
        try:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS retrieval_cache (
                    user_id TEXT NOT NULL,
                    project_id TEXT NOT NULL,
                    priors_revision INTEGER NOT NULL,
                    base_path TEXT NOT NULL,
                    model TEXT NOT NULL,
                    context_hash TEXT NOT NULL,
                    ignore_prior_ids_json TEXT NOT NULL,
                    response_json TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT (datetime('now')),
                    updated_at TIMESTAMP DEFAULT (datetime('now')),
                    PRIMARY KEY (
                        user_id,
                        project_id,
                        priors_revision,
                        base_path,
                        model,
                        context_hash,
                        ignore_prior_ids_json
                    )
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS retrieval_cache_scope_idx
                ON retrieval_cache(user_id, project_id, priors_revision)
                """
            )
            conn.commit()
        finally:
            conn.close()
        _INITIALIZED = True


def _normalized_ignore_ids(ignore_prior_ids: list[str] | None) -> str:
    unique_sorted = sorted({prior_id for prior_id in (ignore_prior_ids or []) if prior_id})
    return json.dumps(unique_sorted)


def _context_hash(context: str) -> str:
    return hash_input(context or "")


def get_cached_retrieval(
    *,
    user_id: str,
    project_id: str,
    priors_revision: int,
    base_path: str,
    model: str,
    context: str,
    ignore_prior_ids: list[str] | None = None,
) -> dict[str, Any] | None:
    _ensure_db()
    conn = sqlite3.connect(_CACHE_PATH, timeout=30.0)
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute(
            """
            SELECT response_json
            FROM retrieval_cache
            WHERE user_id=?
              AND project_id=?
              AND priors_revision=?
              AND base_path=?
              AND model=?
              AND context_hash=?
              AND ignore_prior_ids_json=?
            """,
            (
                user_id,
                project_id,
                priors_revision,
                base_path,
                model,
                _context_hash(context),
                _normalized_ignore_ids(ignore_prior_ids),
            ),
        ).fetchone()
        if row is None:
            return None
        return json.loads(row["response_json"])
    finally:
        conn.close()


def store_cached_retrieval(
    *,
    user_id: str,
    project_id: str,
    priors_revision: int,
    base_path: str,
    model: str,
    context: str,
    ignore_prior_ids: list[str] | None,
    response: dict[str, Any],
) -> None:
    _ensure_db()
    conn = sqlite3.connect(_CACHE_PATH, timeout=30.0)
    try:
        conn.execute(
            """
            INSERT INTO retrieval_cache (
                user_id,
                project_id,
                priors_revision,
                base_path,
                model,
                context_hash,
                ignore_prior_ids_json,
                response_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (
                user_id,
                project_id,
                priors_revision,
                base_path,
                model,
                context_hash,
                ignore_prior_ids_json
            )
            DO UPDATE SET
                response_json=excluded.response_json,
                updated_at=datetime('now')
            """,
            (
                user_id,
                project_id,
                priors_revision,
                base_path,
                model,
                _context_hash(context),
                _normalized_ignore_ids(ignore_prior_ids),
                json.dumps(response, sort_keys=True),
            ),
        )
        conn.commit()
    finally:
        conn.close()
