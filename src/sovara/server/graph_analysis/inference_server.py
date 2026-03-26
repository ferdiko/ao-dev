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
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

# ============================================================
# Sub-server app
# ============================================================

app = FastAPI()


@app.get("/health")
def health():
    return {"status": "ok"}


# ============================================================
# Graph → Trace extraction helpers
# ============================================================

def _to_show_to_trace_fields(to_show_in: dict, to_show_out: dict) -> tuple[str, list, str]:
    """Extract (system_prompt, input_messages, output_text) from to_show dicts.

    to_show uses dot-flattened keys: "body.messages", "body.system",
    "content.choices", "content.content", etc.
    """
    from sovara.server.graph_analysis.trace_chat.utils.trace import extract_text_content

    messages = to_show_in.get("body.messages", [])

    # System prompt: Anthropic uses "body.system"; OpenAI uses role=system message
    system_prompt = extract_text_content(to_show_in.get("body.system") or "")
    input_messages = []
    for m in messages:
        if m.get("role") == "system" and not system_prompt:
            system_prompt = extract_text_content(m.get("content", ""))
        else:
            input_messages.append(m)

    # Output: OpenAI content.choices[0].message.content, Anthropic content.content
    choices = to_show_out.get("content.choices", [])
    if choices:
        raw_content = choices[0].get("message.content", "")
        output_text = extract_text_content(raw_content) if raw_content else ""
    elif "content.content" in to_show_out:
        output_text = extract_text_content(to_show_out["content.content"])
    else:
        output_text = json.dumps(to_show_out) if to_show_out else ""

    return system_prompt, input_messages, output_text


# ============================================================
# Trace cache and background prefetch pool
# ============================================================

# _trace_cache stores {"trace": Trace, "fp": str} per session_id.
# The fingerprint hashes graph node content (input/output) so the cache
# is invalidated on edits and reruns (which rebuild the graph).
_trace_cache: dict = {}
_prefetch_futures: dict = {}
_pool = ThreadPoolExecutor(max_workers=4)


def _graph_fingerprint(graph_data: dict) -> str:
    """Hash graph node content to detect trace-relevant changes."""
    content = "\n".join(
        f"{n['id']}|{n.get('input', '')}|{n.get('output', '')}"
        for n in graph_data.get("nodes", [])
    )
    return hashlib.md5(content.encode()).hexdigest()


def _build_trace_from_graph(graph_data: dict):
    """Build a Trace object from graph topology data.

    The graph is the single source of truth: it is cleared on rerun and
    updated on edit, so it always reflects the current trace state.
    """
    from sovara.server.graph_analysis.trace_chat.utils.trace import Trace

    nodes = graph_data.get("nodes", [])
    if not nodes:
        return None

    lines = []
    for node in nodes:
        try:
            to_show_in = json.loads(node.get("input", "{}"))
            to_show_out = json.loads(node.get("output", "{}"))
        except (json.JSONDecodeError, TypeError):
            continue

        system_prompt, input_messages, output_text = _to_show_to_trace_fields(
            to_show_in, to_show_out,
        )
        lines.append(json.dumps({
            "node_id": node["id"],
            "system_prompt": system_prompt,
            "input": input_messages,
            "output": output_text,
            "model/tool": node.get("model", ""),
        }))

    if not lines:
        return None
    return Trace.from_string("\n".join(lines))


def _get_trace_for_session(session_id: str):
    """Return (trace, is_new) — is_new=True when the trace was rebuilt."""
    from sovara.server.database_manager import DB

    graph_row = DB.get_graph(session_id)
    if not graph_row or not graph_row["graph_topology"]:
        return None, False

    graph_data = json.loads(graph_row["graph_topology"])
    if not graph_data.get("nodes"):
        return None, False

    fp = _graph_fingerprint(graph_data)

    cached = _trace_cache.get(session_id)
    if cached and cached["fp"] == fp:
        return cached["trace"], False

    trace = _build_trace_from_graph(graph_data)
    if trace:
        trace.session_id = session_id
        _trace_cache[session_id] = {"trace": trace, "fp": fp}
    return trace, True


# ============================================================
# Chat endpoint
# ============================================================

class ChatRequest(BaseModel):
    message: str
    history: list = []
    model: str = "anthropic/claude-sonnet-4-6"


@app.post("/prefetch/{session_id}", status_code=202)
def prefetch(session_id: str, model: str = "anthropic/claude-sonnet-4-6"):
    """Fire-and-forget: build trace + start summary prefetch. Returns immediately."""
    def _do():
        trace, is_new = _get_trace_for_session(session_id)
        if trace is None:
            return
        if is_new or session_id not in _prefetch_futures:
            from sovara.server.graph_analysis.trace_chat.tools.summarize_trace import _generate_summary
            _prefetch_futures[session_id] = _pool.submit(_generate_summary, trace, model)
    _pool.submit(_do)
    return {"status": "prefetching"}


@app.post("/chat/{session_id}")
async def chat(session_id: str, req: ChatRequest):
    trace, is_new = await asyncio.to_thread(_get_trace_for_session, session_id)
    if trace is None:
        raise HTTPException(400, "No LLM calls found for this session")

    # (Re-)prefetch summary on first request or when the trace changed after a rerun/edit
    if is_new or session_id not in _prefetch_futures:
        from sovara.server.graph_analysis.trace_chat.tools.summarize_trace import _generate_summary
        _prefetch_futures[session_id] = _pool.submit(_generate_summary, trace, req.model)

    from sovara.server.graph_analysis.trace_chat.main import handle_question
    result = await asyncio.to_thread(
        handle_question, req.message, trace, req.history, req.model,
        _prefetch_futures.get(session_id),
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

    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")
