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
# DB → Trace extraction helpers
# ============================================================

def _raw_to_to_show(raw: dict) -> dict:
    """Return the display-friendly version of a raw DB dict.

    Currently returns raw as-is; the DB already stores a pre-computed
    to_show alongside raw. Override this to apply additional filtering.
    """
    return raw


def _raw_to_trace_fields(raw_in: dict, raw_out: dict) -> tuple[str, list, str, str]:
    """Extract (system_prompt, input_messages, output_text, model) from raw dicts.

    raw_in format (httpx LLM call): {"url": "...", "body": {"messages": [...], "model": "..."}}
    raw_out format (httpx LLM call): {"_obj_str": "...", "content": {<LLM response JSON>}}

    Add branches here when supporting additional api_types (genai, claude_sdk, MCP).
    """
    from sovara.server.graph_analysis.trace_chat.utils.trace import extract_text_content

    body = raw_in.get("body", {}) if isinstance(raw_in, dict) else {}
    messages = body.get("messages", []) if isinstance(body, dict) else []

    # System prompt: Anthropic puts it at top-level "system"; OpenAI uses role=system message
    system_prompt = body.get("system", "") or ""
    input_messages = []
    for m in messages:
        if m.get("role") == "system" and not system_prompt:
            system_prompt = extract_text_content(m.get("content", ""))
        else:
            input_messages.append(m)

    # Output text: OpenAI uses choices[0].message.content, Anthropic uses content[0].text
    content = raw_out.get("content", {}) if isinstance(raw_out, dict) else {}
    if isinstance(content, dict):
        if "choices" in content:  # OpenAI format
            msg = (content["choices"] or [{}])[0].get("message", {})
            output_text = extract_text_content(msg.get("content", ""))
        elif "content" in content:  # Anthropic format
            output_text = extract_text_content(content["content"])
        else:
            output_text = json.dumps(content)  # fallback: stringify unknown format
    else:
        output_text = str(content) if content else ""

    model = body.get("model", "") if isinstance(body, dict) else ""
    return system_prompt, input_messages, output_text, model


# ============================================================
# Trace cache and background prefetch pool
# ============================================================

# _trace_cache stores {"trace": Trace, "fp": str} per session_id.
# The fingerprint covers only the columns that change on edit/rerun
# (input_overwrite, output), so the cache is preserved across unrelated
# requests and invalidated exactly when the trace data changes.
_trace_cache: dict = {}
_prefetch_futures: dict = {}
_pool = ThreadPoolExecutor(max_workers=4)


def _row_fingerprint(rows: list) -> str:
    """Hash the mutable columns (input_overwrite, output) to detect rerun/edit changes."""
    content = "\n".join(
        f"{r['node_id']}|{r['input_overwrite'] or ''}|{r['output'] or ''}"
        for r in rows
    )
    return hashlib.md5(content.encode()).hexdigest()


def _build_trace_from_rows(rows: list):
    """Build a Trace object from pre-fetched (and dict-converted) DB rows."""
    from sovara.server.graph_analysis.trace_chat.utils.trace import Trace

    lines = []
    for row in rows:
        try:
            # Use input_overwrite (edited input) when present, fall back to original
            effective_input = row["input_overwrite"] or row["input"]
            inp = json.loads(effective_input or "{}")
            out = json.loads(row["output"] or "{}") if row["output"] else {}
        except (json.JSONDecodeError, TypeError):
            continue

        raw_in = inp.get("raw", {})
        raw_out = out.get("raw", {})
        system_prompt, input_messages, output_text, model = _raw_to_trace_fields(raw_in, raw_out)

        lines.append(json.dumps({
            "node_id": row["node_id"],
            "system_prompt": system_prompt,
            "input": input_messages,
            "output": output_text,
            "model/tool": model or row.get("api_type", ""),
        }))

    if not lines:
        return None
    return Trace.from_string("\n".join(lines))


def _get_trace_for_session(session_id: str):
    """Return (trace, is_new) — is_new=True when the trace was rebuilt from DB."""
    from sovara.server.database_manager import DB

    raw_rows = DB.get_llm_calls_for_session(session_id)
    if not raw_rows:
        return None, False

    rows = [dict(r) for r in raw_rows]
    fp = _row_fingerprint(rows)

    cached = _trace_cache.get(session_id)
    if cached and cached["fp"] == fp:
        return cached["trace"], False

    trace = _build_trace_from_rows(rows)
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
