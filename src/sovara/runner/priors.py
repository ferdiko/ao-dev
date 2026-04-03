"""
Prior injection for LLM contexts.

Queries the priors server for priors and returns them formatted for
injection into prompts. Automatically tracks which priors were applied
to which runs.
"""

import json
import urllib.error
import urllib.request
from typing import List, Optional

from sovara.common.constants import PRIORS_SERVER_URL
from sovara.common.logger import logger


def _priors_request(endpoint: str, payload: dict) -> dict:
    """POST to the priors server and return parsed JSON response."""
    url = f"{PRIORS_SERVER_URL}/api/v1{endpoint}"
    data = json.dumps(payload).encode("utf-8")
    headers = {"Content-Type": "application/json"}

    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=300) as response:
        return json.loads(response.read().decode("utf-8"))


def _query_priors(path: Optional[str] = None) -> tuple[List[dict], str]:
    """Fetch all priors from a path and return both rows and injected context."""
    payload = {}
    if path is not None:
        payload["path"] = path
    result = _priors_request("/query/priors", payload)
    return result.get("priors", []), result.get("injected_context", "")


def _retrieve_priors(path: Optional[str], context: str, model: Optional[str] = None) -> List[dict]:
    """Retrieve relevant priors via the LLM-backed retriever."""
    payload = {"context": context}
    if path is not None:
        payload["base_path"] = path
    if model is not None:
        payload["model"] = model
    result = _priors_request("/query/priors/retrieve", payload)
    return result.get("priors", [])


def _format_priors(priors: List[dict]) -> str:
    """Format priors into an injectable context block."""
    if not priors:
        return ""
    blocks = [f"## {prior['name']}\n{prior['content']}" for prior in priors]
    return "<priors>\n" + "\n\n".join(blocks) + "\n</priors>"


def _track_priors(prior_ids: List[str]) -> None:
    """Track which priors were applied to the current run."""
    try:
        from sovara.runner.context_manager import get_run_id

        run_id = get_run_id()
        if run_id:
            from sovara.server.database import DB

            for prior_id in prior_ids:
                DB.add_prior_applied(prior_id, run_id)
            logger.debug(f"Tracked {len(prior_ids)} priors applied to run {run_id[:8]}")
    except Exception as e:
        logger.debug(f"Could not track prior application: {e}")


def inject_priors(
    path: Optional[str] = None,
    context: Optional[str] = None,
    method: str = "retrieve",
    model: Optional[str] = None,
) -> str:
    """
    Retrieve priors from the priors server and return them as injected context.

    Args:
        path: Folder path to retrieve priors from (e.g. 'beaver/retriever/').
        context: Context string for LLM-based retrieval (required when method="retrieve").
        method: "retrieve" (LLM-filtered), "all" (all priors in path), or "none".
        model: Optional retriever model override.

    Returns:
        Formatted priors string, or empty string if unavailable.
    """
    if method == "none":
        return ""

    try:
        if method == "retrieve":
            if context is None:
                raise ValueError("context is required when method='retrieve'")
            priors = _retrieve_priors(path, context, model=model)
            injected_context = _format_priors(priors)
        elif method == "all":
            priors, injected_context = _query_priors(path)
        else:
            raise ValueError(f"Unknown method: {method}")
    except (urllib.error.URLError, ConnectionError) as e:
        logger.warning(f"Priors server unavailable: {e}")
        return ""
    except ValueError:
        raise
    except Exception as e:
        logger.warning(f"Failed to fetch priors: {e}")
        return ""

    prior_ids = [prior.get("id") for prior in priors if prior.get("id")]
    if prior_ids:
        _track_priors(prior_ids)

    return injected_context
