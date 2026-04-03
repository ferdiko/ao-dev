"""
SQLite connection management.

Uses per-thread connections via threading.local() so readers can run concurrently
under WAL mode. Writers still serialize at the SQLite level (WAL allows only one
writer at a time), but that's SQLite's own locking, not a Python bottleneck.
"""

import os
import sqlite3
import threading

from sovara.common.constants import SOVARA_DB_PATH
from sovara.common.logger import logger


_local = threading.local()
_schema_initialized = False
_init_lock = threading.Lock()


def get_conn():
    """Get a per-thread SQLite connection, creating one if needed."""
    global _schema_initialized

    conn = getattr(_local, "conn", None)
    if conn is not None:
        return conn

    db_path = os.path.join(SOVARA_DB_PATH, "runs.sqlite")
    os.makedirs(os.path.dirname(db_path), exist_ok=True)

    conn = sqlite3.connect(
        db_path,
        timeout=30.0,
    )
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA busy_timeout=10000")

    if not _schema_initialized:
        with _init_lock:
            if not _schema_initialized:
                from .schema import init_db

                init_db(conn)
                _schema_initialized = True

    _local.conn = conn
    return conn


def query_one(sql, params=()):
    conn = get_conn()
    c = conn.cursor()
    c.execute(sql, params)
    return c.fetchone()


def query_all(sql, params=()):
    conn = get_conn()
    c = conn.cursor()
    c.execute(sql, params)
    return c.fetchall()


def execute(sql, params=()):
    conn = get_conn()
    c = conn.cursor()
    c.execute(sql, params)
    conn.commit()
    return c.lastrowid


def clear_connections():
    """Close the calling thread's connection."""
    conn = getattr(_local, "conn", None)
    if conn:
        try:
            conn.close()
        except Exception as e:
            logger.warning(f"Error closing SQLite connection: {e}")
        finally:
            _local.conn = None
        logger.debug("Closed thread-local SQLite connection")
