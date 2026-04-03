"""Persistent prompt-prefix cache for replaying injected priors across runs."""

from __future__ import annotations

import json
import os
import sqlite3
import threading
from typing import Any

from sovara.common.constants import SOVARA_HOME

_CACHE_DIR = os.path.join(SOVARA_HOME, "priors")
_CACHE_PATH = os.path.join(_CACHE_DIR, "prefix-cache.sqlite")
_INIT_LOCK = threading.Lock()
_INITIALIZED = False


def _connect() -> sqlite3.Connection:
    os.makedirs(_CACHE_DIR, exist_ok=True)
    return sqlite3.connect(_CACHE_PATH, timeout=30.0)


def _ensure_db() -> None:
    global _INITIALIZED
    if _INITIALIZED:
        return
    with _INIT_LOCK:
        if _INITIALIZED:
            return
        conn = _connect()
        try:
            existing_columns = {
                row[1]
                for row in conn.execute("PRAGMA table_info(prefix_cache)").fetchall()
            }
            if existing_columns and "model" not in existing_columns:
                conn.execute("DROP TABLE IF EXISTS prefix_cache")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS prefix_cache (
                    user_id TEXT NOT NULL,
                    project_id TEXT NOT NULL,
                    base_path TEXT NOT NULL,
                    model TEXT NOT NULL,
                    first_key TEXT NOT NULL,
                    pair_count INTEGER NOT NULL,
                    clean_pairs_json TEXT NOT NULL,
                    injected_pairs_json TEXT NOT NULL,
                    prior_ids_json TEXT NOT NULL DEFAULT '[]',
                    created_at TIMESTAMP DEFAULT (datetime('now')),
                    updated_at TIMESTAMP DEFAULT (datetime('now')),
                    PRIMARY KEY (user_id, project_id, base_path, model, clean_pairs_json)
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS prefix_cache_scope_idx
                ON prefix_cache(user_id, project_id, base_path, model, first_key, pair_count DESC)
                """
            )
            conn.commit()
        finally:
            conn.close()
        _INITIALIZED = True


def _normalize_pairs(pairs: list[dict[str, Any]] | None) -> list[dict[str, str]]:
    normalized: list[dict[str, str]] = []
    for pair in pairs or []:
        key = pair.get("key")
        value = pair.get("value")
        if isinstance(key, str) and isinstance(value, str):
            normalized.append({"key": key, "value": value})
    return normalized


def _normalized_prior_ids(prior_ids: list[str] | None) -> list[str]:
    ordered_unique: list[str] = []
    for prior_id in prior_ids or []:
        if prior_id and prior_id not in ordered_unique:
            ordered_unique.append(prior_id)
    return ordered_unique


def lookup_longest_prefix(
    *,
    user_id: str,
    project_id: str,
    base_path: str,
    model: str,
    clean_pairs: list[dict[str, Any]],
) -> dict[str, Any] | None:
    normalized_pairs = _normalize_pairs(clean_pairs)
    if not normalized_pairs:
        return None

    _ensure_db()
    conn = _connect()
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            """
            SELECT pair_count, clean_pairs_json, injected_pairs_json, prior_ids_json
            FROM prefix_cache
            WHERE user_id=?
              AND project_id=?
              AND base_path=?
              AND model=?
              AND first_key=?
              AND pair_count<=?
            ORDER BY pair_count DESC, updated_at DESC
            """,
            (
                user_id,
                project_id,
                base_path,
                model,
                normalized_pairs[0]["key"],
                len(normalized_pairs),
            ),
        ).fetchall()
        for row in rows:
            cached_clean_pairs = json.loads(row["clean_pairs_json"])
            pair_count = int(row["pair_count"])
            if normalized_pairs[:pair_count] != cached_clean_pairs:
                continue
            conn.execute(
                """
                UPDATE prefix_cache
                SET updated_at=datetime('now')
                WHERE user_id=? AND project_id=? AND base_path=? AND model=? AND clean_pairs_json=?
                """,
                (user_id, project_id, base_path, model, row["clean_pairs_json"]),
            )
            conn.commit()
            return {
                "matched_pair_count": pair_count,
                "injected_pairs": json.loads(row["injected_pairs_json"]),
                "prior_ids": json.loads(row["prior_ids_json"]),
            }
        return None
    finally:
        conn.close()


def store_prefix(
    *,
    user_id: str,
    project_id: str,
    base_path: str,
    model: str,
    clean_pairs: list[dict[str, Any]],
    injected_pairs: list[dict[str, Any]],
    prior_ids: list[str] | None,
) -> None:
    normalized_clean_pairs = _normalize_pairs(clean_pairs)
    normalized_injected_pairs = _normalize_pairs(injected_pairs)
    if not normalized_clean_pairs or len(normalized_clean_pairs) != len(normalized_injected_pairs):
        return

    _ensure_db()
    conn = _connect()
    try:
        clean_pairs_json = json.dumps(normalized_clean_pairs, ensure_ascii=False, separators=(",", ":"))
        conn.execute(
            """
            INSERT INTO prefix_cache (
                user_id,
                project_id,
                base_path,
                model,
                first_key,
                pair_count,
                clean_pairs_json,
                injected_pairs_json,
                prior_ids_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (user_id, project_id, base_path, model, clean_pairs_json)
            DO UPDATE SET
                injected_pairs_json=excluded.injected_pairs_json,
                prior_ids_json=excluded.prior_ids_json,
                updated_at=datetime('now')
            """,
            (
                user_id,
                project_id,
                base_path,
                model,
                normalized_clean_pairs[0]["key"],
                len(normalized_clean_pairs),
                clean_pairs_json,
                json.dumps(normalized_injected_pairs, ensure_ascii=False, separators=(",", ":")),
                json.dumps(_normalized_prior_ids(prior_ids), ensure_ascii=False, separators=(",", ":")),
            ),
        )
        conn.commit()
    finally:
        conn.close()


def clear_scope_prefix_cache(*, user_id: str, project_id: str) -> None:
    _ensure_db()
    conn = _connect()
    try:
        conn.execute(
            "DELETE FROM prefix_cache WHERE user_id=? AND project_id=?",
            (user_id, project_id),
        )
        conn.commit()
    finally:
        conn.close()


def clear_all_prefix_cache() -> None:
    _ensure_db()
    conn = _connect()
    try:
        conn.execute("DELETE FROM prefix_cache")
        conn.commit()
    finally:
        conn.close()
