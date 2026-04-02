"""
Inference sub-server for heavier graph analysis computations.

Spawned as a child process by the main server on startup and terminated on shutdown.
Exposes a REST API on INFERENCE_PORT. Add compute-heavy routes here rather than
burdening the main server's event loop.

Lifecycle (called by main server lifespan in app.py):
    inference_server.start()   # spawns subprocess
    inference_server.stop()    # terminates it
"""

import asyncio
import hashlib
import json
import os
import subprocess
import sys
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from sovara.common.constants import INFERENCE_SERVER_LOG
from sovara.common.logger import create_file_logger
from sovara.server.graph_models import RunGraph
from sovara.server.graph_analysis.trace_chat.cancel import TraceChatCancelled

# ============================================================
# Sub-server app
# ============================================================

app = FastAPI()
logger = create_file_logger(INFERENCE_SERVER_LOG)


@app.get("/health")
def health():
    return {"status": "ok"}


# ============================================================
# Trace cache and background prefetch pool
# ============================================================

# _trace_cache stores {"trace": Trace, "fp": str} per run_id.
# The fingerprint hashes graph node content (input/output) so the cache
# is invalidated on edits and reruns (which rebuild the graph).
_trace_cache: dict = {}
_prefetch_futures: dict[str, Future] = {}
_chat_cancel_events: dict[str, threading.Event] = {}
_pool = ThreadPoolExecutor(max_workers=4)


def _log_preview(text: str, max_len: int = 160) -> str:
    compact = " ".join(str(text).split()).strip()
    if len(compact) <= max_len:
        return compact
    return compact[:max_len] + "..."


def _graph_fingerprint(graph_data: dict) -> str:
    """Hash graph node content to detect trace-relevant changes."""
    def _node_identity(node: dict) -> str:
        # Persisted graph nodes use `uuid`; keep `id` as a fallback for any
        # older payloads that may still flow through this code path.
        return str(node.get("uuid") or node.get("id") or "")

    content = "\n".join(
        f"{_node_identity(n)}|{n.get('input', '')}|{n.get('output', '')}|{n.get('name', '')}"
        for n in graph_data.get("nodes", [])
    )
    return hashlib.md5(content.encode()).hexdigest()


def _build_trace_from_graph(graph_data: dict):
    """Build a Trace object from graph topology data.

    The graph is the single source of truth: it is cleared on rerun and
    updated on edit, so it always reflects the current trace state.
    """
    from sovara.server.graph_analysis.trace_chat.utils.trace import (
        Trace,
        build_trace_record_from_to_show,
    )

    graph = RunGraph.from_dict(graph_data)
    nodes = sorted(graph.nodes, key=lambda node: (node.step_id, node.uuid))
    if not nodes:
        return None

    records = []
    for node in nodes:
        try:
            to_show_in = json.loads(node.input or "{}")
            to_show_out = json.loads(node.output or "{}")
        except (json.JSONDecodeError, TypeError):
            continue

        records.append(build_trace_record_from_to_show(
            to_show_in,
            to_show_out,
            index=len(records),
            name=node.name or "",
            node_uuid=node.uuid,
        ))

    if not records:
        return None
    return Trace.from_records(records)


def _get_trace_for_run(run_id: str):
    """Return (trace, is_new) — is_new=True when the trace was rebuilt."""
    from sovara.server.database_manager import DB

    graph_row = DB.get_graph(run_id)
    if not graph_row or not graph_row["graph_topology"]:
        return None, False

    graph = RunGraph.from_json_string(graph_row["graph_topology"])
    graph_data = graph.to_dict()
    if not graph_data.get("nodes"):
        return None, False

    fp = _graph_fingerprint(graph_data)

    cached = _trace_cache.get(run_id)
    if cached and cached["fp"] == fp:
        return cached["trace"], False

    trace = _build_trace_from_graph(graph_data)
    if trace:
        trace.run_id = run_id
        _trace_cache[run_id] = {"trace": trace, "fp": fp}
    return trace, True


def _ensure_prefetch_future(run_id: str, trace, *, is_new: bool) -> Future:
    if is_new:
        stale = _prefetch_futures.pop(run_id, None)
        if stale is not None and not stale.done():
            logger.info("Prefetch dropped stale running future run_id=%s", run_id)

    future = _prefetch_futures.get(run_id)
    if future is not None:
        if future.cancelled():
            future = None
        elif future.done():
            try:
                if future.exception() is not None:
                    future = None
            except Exception:
                future = None

    if future is None:
        from sovara.server.graph_analysis.trace_chat.tools.summarize_trace import _generate_summary

        future = _pool.submit(_generate_summary, trace)
        future._sovara_started_at = time.monotonic()
        future._sovara_run_id = run_id
        _prefetch_futures[run_id] = future
        logger.info(
            "Prefetch queued run_id=%s steps=%d is_new=%s",
            run_id,
            len(trace),
            is_new,
        )

        def _log_done(done_future: Future) -> None:
            started_at = getattr(done_future, "_sovara_started_at", None)
            elapsed = (
                max(0.0, time.monotonic() - started_at)
                if started_at is not None else 0.0
            )
            if done_future.cancelled():
                logger.warning(
                    "Prefetch future cancelled run_id=%s after %.1fs",
                    run_id,
                    elapsed,
                )
                return
            try:
                summary = done_future.result()
                logger.info(
                    "Prefetch future complete run_id=%s elapsed=%.1fs summary_chars=%d",
                    run_id,
                    elapsed,
                    len(summary),
                )
            except Exception as exc:
                logger.error(
                    "Prefetch future failed run_id=%s after %.1fs: %s",
                    run_id,
                    elapsed,
                    exc,
                )

        if hasattr(future, "add_done_callback"):
            future.add_done_callback(_log_done)
    else:
        started_at = getattr(future, "_sovara_started_at", None)
        elapsed = (
            max(0.0, time.monotonic() - started_at)
            if started_at is not None else 0.0
        )
        state = "done" if future.done() else "running"
        logger.info(
            "Prefetch reusing existing future run_id=%s state=%s age=%.1fs",
            run_id,
            state,
            elapsed,
        )

    return future


# ============================================================
# Chat endpoint
# ============================================================

class ChatRequest(BaseModel):
    message: str
    history: list = Field(default_factory=list)


@app.post("/chat/{run_id}/abort", status_code=202)
def abort_chat(run_id: str):
    cancel_event = _chat_cancel_events.get(run_id)
    if cancel_event is None:
        logger.info("Trace chat abort requested for idle run_id=%s", run_id)
        return {"status": "idle"}
    cancel_event.set()
    logger.info("Trace chat abort requested for run_id=%s", run_id)
    return {"status": "cancelling"}


@app.post("/prefetch/{run_id}", status_code=202)
def prefetch(run_id: str):
    """Fire-and-forget: build trace + start summary prefetch. Returns immediately."""
    def _do():
        try:
            trace, is_new = _get_trace_for_run(run_id)
            if trace is None:
                logger.warning("Prefetch skipped for run_id=%s: no trace found", run_id)
                return
            logger.info(
                "Trace chat opened from prefetch run_id=%s steps=%d is_new=%s",
                run_id,
                len(trace),
                is_new,
            )
            _ensure_prefetch_future(run_id, trace, is_new=is_new)
            logger.info("Prefetch queued for run_id=%s steps=%d", run_id, len(trace))
        except Exception:
            logger.exception("Prefetch failed for run_id=%s", run_id)
    _pool.submit(_do)
    return {"status": "prefetching"}


@app.post("/chat/{run_id}")
async def chat(run_id: str, req: ChatRequest):
    logger.info(
        "Trace chat request: run_id=%s history_messages=%d message=%s",
        run_id,
        len(req.history),
        _log_preview(req.message),
    )

    cancel_event = threading.Event()
    _chat_cancel_events[run_id] = cancel_event
    try:
        try:
            trace, is_new = await asyncio.to_thread(_get_trace_for_run, run_id)
        except TraceChatCancelled as exc:
            logger.info("Trace chat request cancelled for run_id=%s", run_id)
            raise HTTPException(409, str(exc))
        except Exception:
            logger.exception("Failed to load trace for run_id=%s", run_id)
            raise

        if trace is None:
            logger.warning("Trace chat rejected for run_id=%s: no LLM calls found", run_id)
            raise HTTPException(400, "No LLM calls found for this run")

        # (Re-)prefetch summary on first request or when the trace changed after a rerun/edit
        prefetch_future = _ensure_prefetch_future(run_id, trace, is_new=is_new)

        from sovara.server.graph_analysis.trace_chat.main import handle_question
        try:
            result = await asyncio.to_thread(
                handle_question,
                req.message,
                trace,
                req.history,
                prefetch_future,
                cancel_event,
            )
        except TraceChatCancelled as exc:
            logger.info("Trace chat request cancelled for run_id=%s", run_id)
            raise HTTPException(409, str(exc))
        except Exception:
            logger.exception("Trace chat request failed for run_id=%s", run_id)
            raise
    finally:
        if _chat_cancel_events.get(run_id) is cancel_event:
            _chat_cancel_events.pop(run_id, None)

    logger.info(
        "Trace chat response ready: run_id=%s answer_chars=%d edits_applied=%s",
        run_id,
        len(result.get("answer", "")),
        result.get("edits_applied", False),
    )
    return result


# ============================================================
# Lifecycle (called from main server lifespan)
# ============================================================

_process: Optional[subprocess.Popen] = None


def start() -> None:
    """Spawn the inference server as a child process."""
    global _process
    from sovara.common.constants import HOST, INFERENCE_PORT, INFERENCE_SERVER_LOG

    os.makedirs(os.path.dirname(INFERENCE_SERVER_LOG), exist_ok=True)
    log_f = open(INFERENCE_SERVER_LOG, "a")
    _process = subprocess.Popen(
        [sys.executable, "-m", "sovara.server.graph_analysis.inference_server",
         "--host", HOST, "--port", str(INFERENCE_PORT)],
        stdout=log_f,
        stderr=subprocess.STDOUT,
        close_fds=True,
    )


def stop() -> None:
    """Terminate the inference server child process."""
    global _process
    if _process is None:
        return
    _process.terminate()
    try:
        _process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        _process.kill()
    _process = None


# ============================================================
# Entry point (when spawned as subprocess)
# ============================================================

if __name__ == "__main__":
    import argparse
    import uvicorn

    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=5961)
    args = parser.parse_args()

    logger.info("Inference server starting on %s:%s", args.host, args.port)
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")
