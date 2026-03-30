"""
String matching for content-based edge detection.

This module implements the matching algorithm that determines which previous
LLM outputs appear in a new LLM's input, establishing dataflow edges.

Uses word-level longest contiguous match via difflib.SequenceMatcher.
"""

import re
import json
import threading
from difflib import SequenceMatcher
from typing import List, Dict, Any
from flatten_json import flatten
from sovara.common.logger import logger
from sovara.common.constants import COMPILED_STRING_MATCH_EXCLUDE_PATTERNS
from sovara.runner.monkey_patching.api_parser import func_kwargs_to_json_str, api_obj_to_json_str
from sovara.runner.priors_pipeline import strip_priors_blocks_exact


# ===========================================================
# Matching Configuration
# ===========================================================

# Minimum contiguous match length (in words) to create an edge
MIN_MATCH_WORDS = 3

# Minimum fraction of output words that must appear in the input
MIN_OUTPUT_COVERAGE = 0.8
# ===========================================================
# Match Criteria
# ===========================================================


def _is_url_like(text: str) -> bool:
    """Check if text contains URL-like patterns (used at storage time)."""
    return "://" in text or "www." in text


def _coverage_criteria(match_len: int, output_len: int) -> bool:
    """Check if match covers enough of the output."""
    return output_len > 0 and match_len / output_len >= MIN_OUTPUT_COVERAGE


def _content_criteria(match_len: int, is_url_like: bool) -> bool:
    """Match >= MIN_MATCH_WORDS, or any match for URL-like content."""
    return match_len >= MIN_MATCH_WORDS or (is_url_like and match_len > 0)


# ===========================================================
# Tokenization
# ===========================================================


def _extract_json_strings(text: str) -> List[str]:
    """Extract string values from JSON, or return text as-is if not JSON."""
    if not text:
        return []

    text = text.strip()

    # Quick check: JSON must start with { or [
    if not (text.startswith("{") or text.startswith("[")):
        return [text]

    try:
        data = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return [text]

    strings = []

    def extract(obj):
        if isinstance(obj, str) and obj.strip():
            strings.append(obj.strip())
        elif isinstance(obj, dict):
            for v in obj.values():
                extract(v)
        elif isinstance(obj, list):
            for item in obj:
                extract(item)

    extract(data)
    return strings if strings else [text]


def split_html_content(text: str) -> List[str]:
    """Extract text between HTML tags as separate chunks."""
    if not text:
        return []
    if not re.search(r"<[^>]+>", text):
        return [text]
    chunks = re.split(r"<[^>]+>", text)
    return [chunk.strip() for chunk in chunks if chunk.strip()]


def tokenize(text: str) -> List[str]:
    """Lowercase, strip HTML/punctuation, split on whitespace."""
    if not text:
        return []
    text = re.sub(r"<[^>]+>", " ", text)  # Remove HTML tags
    cleaned = re.sub(r"[^\w\s]", "", text.lower())  # Remove punctuation
    return cleaned.split()


def _strip_priors_blocks(text: str) -> str:
    if not text or "<sovara-priors>" not in text:
        return text
    return strip_priors_blocks_exact(text).strip()


def compute_longest_match(output_words: List[str], input_words: List[str]) -> int:
    """Return length of longest contiguous matching word sequence."""
    if not output_words or not input_words:
        return 0
    sm = SequenceMatcher(None, output_words, input_words, autojunk=False)
    match = sm.find_longest_match(0, len(output_words), 0, len(input_words))
    return match.size


# ===========================================================
# String extraction
# ===========================================================


def _filter_excluded_keys(flattened: Dict[str, Any]) -> List[str]:
    """Filter out keys matching STRING_MATCH_ADDITIONAL_EXCLUDE_PATTERNS."""
    return [
        v
        for k, v in flattened.items()
        if isinstance(v, str)
        and not any(p.match(k) for p in COMPILED_STRING_MATCH_EXCLUDE_PATTERNS)
    ]


def extract_input_strings(input_dict: Dict[str, Any], api_type: str) -> List[str]:
    """Extract text strings from LLM input for matching."""
    try:
        flattened = flatten(
            json.loads(func_kwargs_to_json_str(input_dict, api_type)[0])["to_show"], "."
        )
        values = _filter_excluded_keys(flattened)
        normalized_values = [_strip_priors_blocks(value).strip() for value in values]
        return [value for value in normalized_values if value]
    except Exception as e:
        logger.error(f"Error extracting input strings: {e}")
        return []


def extract_output_text(output_obj: Any, api_type: str) -> List[str]:
    """Extract text strings from LLM output for matching."""
    try:
        flattened = flatten(json.loads(api_obj_to_json_str(output_obj, api_type))["to_show"], ".")
        return _filter_excluded_keys(flattened)
    except Exception as e:
        logger.error(f"Error extracting output text: {e}")
        return []


# ===========================================================
# Run Data Management
# ===========================================================

# In-memory storage for run outputs
# Structure: {run_id: {node_id: [(word_list, is_url_like), ...]}}
_run_outputs: Dict[str, Dict[str, List[tuple[List[str], bool]]]] = {}

# In-memory storage for run inputs
# Structure: {run_id: {node_id: [word_list]}}
_run_inputs: Dict[str, Dict[str, List[str]]] = {}

# Lock protecting _run_outputs and _run_inputs from concurrent access.
# find_source_nodes iterates while store_output_strings writes; without this
# lock, concurrent LLM calls cause RuntimeError during dict iteration.
_run_lock = threading.Lock()


def _get_run_outputs(run_id: str) -> Dict[str, List[tuple[List[str], bool]]]:
    if run_id not in _run_outputs:
        _run_outputs[run_id] = {}
    return _run_outputs[run_id]


def _get_run_inputs(run_id: str) -> Dict[str, List[str]]:
    if run_id not in _run_inputs:
        _run_inputs[run_id] = {}
    return _run_inputs[run_id]


def clear_matching_data(run_id: str) -> None:
    """Clear run data when a run is erased or restarted."""
    with _run_lock:
        _run_outputs.pop(run_id, None)
        _run_inputs.pop(run_id, None)


# ===========================================================
# Content matching
# ===========================================================


def is_content_match(
    output_words: List[str],
    input_words: List[str],
    is_url_like: bool = False,
) -> tuple[bool, str, int, float]:
    """Returns (is_match, match_type, match_len, coverage_product)."""
    match_len = compute_longest_match(output_words, input_words)
    output_coverage = match_len / len(output_words) if output_words else 0
    input_coverage = match_len / len(input_words) if input_words else 0
    coverage_product = output_coverage * input_coverage

    if _coverage_criteria(match_len, len(output_words)) and _content_criteria(
        match_len, is_url_like
    ):
        return True, "coverage", match_len, coverage_product

    # For small strings where length-based matching doesn't work well,
    # use coverage product threshold instead
    if coverage_product > 0.7:
        return True, "coverage_product", match_len, coverage_product

    return False, "", match_len, 0.0


def find_source_nodes(
    run_id: str,
    input_dict: Dict[str, Any],
    api_type: str,
) -> List[str]:
    """Find node IDs whose outputs appear in the given input."""
    # Extract and tokenize input strings (keep fields separate)
    input_strings = extract_input_strings(input_dict, api_type)
    if not input_strings:
        return []

    # Tokenize each input field separately
    input_word_lists = []
    for input_str in input_strings:
        chunks = split_html_content(input_str)
        for chunk in chunks:
            values = _extract_json_strings(chunk)
            for value in values:
                words = tokenize(value)
                if words:
                    input_word_lists.append(words)

    if not input_word_lists:
        return []

    logger.debug(f"[string_matching] input has {len(input_word_lists)} fields")

    # Find matches — snapshot under lock, then match outside it
    with _run_lock:
        session_outputs = dict(_get_run_outputs(run_id))
    matches = []

    for node_id, output_entries in session_outputs.items():
        for output_words, is_url_like in output_entries:
            for input_words in input_word_lists:
                is_match, match_type, match_len, coverage = is_content_match(
                    output_words, input_words, is_url_like
                )
                if is_match:
                    logger.info(
                        f"[string_matching] MATCH ({match_type}): node={node_id[:8]}, "
                        f"match={match_len} words, coverage={coverage:.3f}"
                    )
                    matches.append(node_id)
                    break  # Found match for this output, try next output
            else:
                continue  # No match found, continue to next output
            break  # Match found, don't check more outputs from this node

    return matches


def store_input_strings(
    run_id: str,
    node_id: str,
    input_dict: Dict[str, Any],
    api_type: str,
) -> None:
    """Store tokenized input for containment checks."""
    input_strings = extract_input_strings(input_dict, api_type)
    if not input_strings:
        return

    # For containment checks, concatenate all fields
    input_words = tokenize("\n".join(input_strings))
    if input_words:
        with _run_lock:
            session_inputs = _get_run_inputs(run_id)
            session_inputs[node_id] = input_words


def store_output_strings(
    run_id: str,
    node_id: str,
    output_obj: Any,
    api_type: str,
) -> None:
    """Store tokenized output for future matching."""
    output_strings = extract_output_text(output_obj, api_type)
    if not output_strings:
        return

    # Split HTML content into separate chunks, then tokenize each
    word_lists = []

    for output_str in output_strings:
        # Split HTML into separate content chunks
        chunks = split_html_content(output_str)
        for chunk in chunks:
            # Extract string values from JSON (returns as-is if not JSON)
            values = _extract_json_strings(chunk)
            for value in values:
                words = tokenize(value)
                if words:
                    is_url = _is_url_like(value)
                    word_lists.append((words, is_url))
                    logger.debug(
                        f"[string_matching] stored output: {len(words)} words, "
                        f"url={is_url}, node={node_id[:8]}"
                    )

    if word_lists:
        with _run_lock:
            session_outputs = _get_run_outputs(run_id)
            session_outputs[node_id] = word_lists


def output_contained_in_input(run_id: str, node_a_id: str, node_b_id: str) -> bool:
    """
    Check if A's output is contained in B's input (for transitive edge removal).

    A -> B -> C  :  if A's output ⊆ B's input, we don't need A -> C
    A ------> C
    """
    with _run_lock:
        output_a_entries = _get_run_outputs(run_id).get(node_a_id, [])
        input_b = _get_run_inputs(run_id).get(node_b_id, [])

    if not output_a_entries or not input_b:
        return False

    total_match_len = sum(compute_longest_match(words, input_b) for words, _ in output_a_entries)
    total_output_len = sum(len(words) for words, _ in output_a_entries)
    coverage = total_match_len / total_output_len
    if total_output_len > 0 and coverage >= 0.9:
        return True
    return False
