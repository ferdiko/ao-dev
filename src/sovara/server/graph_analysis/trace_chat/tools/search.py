"""search tool — substring search across all trace content."""

from ..utils.trace import Trace

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


def search(trace: Trace, query) -> str:
    query_lower = query.lower()
    results = []

    for rec in trace.records:
        step_num = rec.index + 1  # 1-based for display

        for block in rec.input_blocks:
            if block.kind == "text":
                haystack = block.text
            else:
                haystack = str(block.raw_value)
            if query_lower in haystack.lower():
                results.append(f"Step {step_num} [input/{block.path}]: {_snippet(haystack, query_lower)}")

        for block in rec.output_blocks:
            if block.kind == "text":
                haystack = block.text
            else:
                haystack = str(block.raw_value)
            if query_lower in haystack.lower():
                results.append(f"Step {step_num} [output/{block.path}]: {_snippet(haystack, query_lower)}")

        if len(results) >= MAX_RESULTS:
            break

    # Search prompt sections (if any have been indexed)
    for pid, ps in getattr(trace, "prompt_sections_cache", {}).items():
        for idx, section in enumerate(ps.sections):
            if query_lower in section.text.lower():
                results.append(
                    f"Prompt [{pid}] path {idx} ({section.path}): "
                    f"{_snippet(section.text, query_lower)}"
                )
            if len(results) >= MAX_RESULTS:
                break

    if not results:
        return f"No matches for '{query}'."

    truncated = f" (showing first {MAX_RESULTS})" if len(results) >= MAX_RESULTS else ""
    return f"Found {len(results)} match(es) for '{query}'{truncated}:\n\n" + "\n".join(results)
