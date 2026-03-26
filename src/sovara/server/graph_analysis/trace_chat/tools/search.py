"""search tool — substring search across all trace content."""

import json

from ..utils.trace import Trace, extract_text_content

MAX_RESULTS = 20
SNIPPET_RADIUS = 50


def _snippet(text: str, query_lower: str) -> str:
    """Return a context snippet around the first match."""
    idx = text.lower().index(query_lower)
    start = max(0, idx - SNIPPET_RADIUS)
    end = min(len(text), idx + len(query_lower) + SNIPPET_RADIUS)
    prefix = "..." if start > 0 else ""
    suffix = "..." if end < len(text) else ""
    return f"{prefix}{text[start:end]}{suffix}"


def search(trace: Trace, **params) -> str:
    query = params.get("query")
    if not query:
        return "Error: 'query' parameter is required."

    query_lower = query.lower()
    results = []

    for rec in trace.records:
        step_num = rec.index + 1  # 1-based for display

        # Search system prompt
        if rec.system_prompt and query_lower in rec.system_prompt.lower():
            results.append(f"Step {step_num} [system_prompt]: {_snippet(rec.system_prompt, query_lower)}")

        # Search input messages
        for j, msg in enumerate(rec.input if isinstance(rec.input, list) else [rec.input]):
            if isinstance(msg, dict):
                text = extract_text_content(msg.get("content", ""))
                role = msg.get("role", "?")
            else:
                text = str(msg)
                role = "?"
            if query_lower in text.lower():
                results.append(f"Step {step_num} [input/{role} msg {j}]: {_snippet(text, query_lower)}")

        # Search output
        out_text = rec.output if isinstance(rec.output, str) else json.dumps(rec.output)
        if query_lower in out_text.lower():
            results.append(f"Step {step_num} [output]: {_snippet(out_text, query_lower)}")

        if len(results) >= MAX_RESULTS:
            break

    # Search prompt sections (if any have been indexed)
    for pid, ps in getattr(trace, "prompt_sections_cache", {}).items():
        for idx, section in enumerate(ps.sections):
            if query_lower in section.text.lower():
                results.append(
                    f"Prompt [{pid}] section {idx} ({section.label}): "
                    f"{_snippet(section.text, query_lower)}"
                )
            if len(results) >= MAX_RESULTS:
                break

    if not results:
        return f"No matches for '{query}'."

    truncated = f" (showing first {MAX_RESULTS})" if len(results) >= MAX_RESULTS else ""
    return f"Found {len(results)} match(es) for '{query}'{truncated}:\n\n" + "\n".join(results)
