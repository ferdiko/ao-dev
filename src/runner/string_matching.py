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
from ao.common.logger import logger
from ao.common.constants import COMPILED_STRING_MATCH_EXCLUDE_PATTERNS
from ao.runner.monkey_patching.api_parser import func_kwargs_to_json_str, api_obj_to_json_str


# ===========================================================
# Matching Configuration
# ===========================================================

# Minimum contiguous match length (in words) to create an edge
MIN_MATCH_WORDS = 3

# Coverage threshold: output_coverage * input_coverage must exceed this
# coverage = (match_len / output_len) * (match_len / input_len)
# This catches cases where the match is significant relative to both texts
MIN_COVERAGE_PRODUCT = 0.1


# ===========================================================
# Tokenization
# ===========================================================


def get_graph_topology(session_id: str):
    import json
    from ao.server.database_manager import DB

    row = DB.get_graph(session_id=session_id)
    if row:
        return json.loads(row["graph_topology"])
    return None


def split_html_content(text: str) -> List[str]:
    """
    Split text containing HTML into separate content chunks.

    Each chunk of text between HTML tags becomes a separate string.
    This allows matching on individual HTML segments independently.

    Example:
        "<div>Hello</div><p>World</p>" -> ["Hello", "World"]
    """
    if not text:
        return []

    # Check if text contains HTML tags
    if not re.search(r"<[^>]+>", text):
        return [text]  # No HTML, return as single chunk

    # Split on HTML tags and filter out empty strings
    chunks = re.split(r"<[^>]+>", text)
    return [chunk.strip() for chunk in chunks if chunk.strip()]


def tokenize(text: str) -> List[str]:
    """
    Tokenize text into words for matching.
    Strips HTML tags, punctuation, lowercases, and splits on whitespace.
    """
    if not text:
        return []
    # Remove HTML tags (e.g., <div>, </span>, <br/>, etc.)
    text = re.sub(r"<[^>]+>", " ", text)
    # Remove punctuation (keep only word characters and whitespace)
    cleaned = re.sub(r"[^\w\s]", "", text.lower())
    return cleaned.split()


def compute_longest_match(output_words: List[str], input_words: List[str]) -> int:
    """
    Compute longest contiguous matching word sequence.

    Uses difflib.SequenceMatcher which is optimized for this purpose.

    Returns:
        Length of longest contiguous match in words.
    """
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
        v for k, v in flattened.items()
        if isinstance(v, str) and not any(p.match(k) for p in COMPILED_STRING_MATCH_EXCLUDE_PATTERNS)
    ]


def extract_input_text(input_dict: Dict[str, Any], api_type: str) -> str:
    """
    Extract textual content from an LLM input for content matching.

    Returns a single concatenated string for searching (we search if any
    stored output string appears in this input text).
    """
    try:
        flattened = flatten(json.loads(func_kwargs_to_json_str(input_dict, api_type)[0])["to_show"], ".")
        strings = _filter_excluded_keys(flattened)
        return "\n".join(strings)
    except Exception as e:
        logger.error(f"Error extracting input text: {e}")
        return ""


def extract_output_text(output_obj: Any, api_type: str) -> List[str]:
    """
    Extract textual content from an LLM output for content matching.

    Returns a list of strings - each will be checked independently for
    substring matches in future inputs. Uses blacklist filtering to
    exclude metadata fields that would cause spurious matches.
    """
    try:
        flattened = flatten(json.loads(api_obj_to_json_str(output_obj, api_type))["to_show"], ".")
        return _filter_excluded_keys(flattened)
    except Exception as e:
        logger.error(f"Error extracting output text: {e}")
        return []

# ===========================================================
# Session Data Management
# ===========================================================

# In-memory storage for session outputs
# Structure: {session_id: {node_id: [[word_lists]]}}
_session_outputs: Dict[str, Dict[str, List[List[str]]]] = {}

# In-memory storage for session inputs
# Structure: {session_id: {node_id: [word_list]}}
_session_inputs: Dict[str, Dict[str, List[str]]] = {}

# Lock protecting _session_outputs and _session_inputs from concurrent access.
# find_source_nodes iterates while store_output_strings writes; without this
# lock, concurrent LLM calls cause RuntimeError during dict iteration.
_session_lock = threading.Lock()


def _get_session_outputs(session_id: str) -> Dict[str, List[List[str]]]:
    """Get or create output storage for a session."""
    if session_id not in _session_outputs:
        _session_outputs[session_id] = {}
    return _session_outputs[session_id]


def _get_session_inputs(session_id: str) -> Dict[str, List[str]]:
    """Get or create input storage for a session."""
    if session_id not in _session_inputs:
        _session_inputs[session_id] = {}
    return _session_inputs[session_id]


def clear_session_data(session_id: str) -> None:
    """Clear session data when a session is erased or restarted."""
    with _session_lock:
        _session_outputs.pop(session_id, None)
        _session_inputs.pop(session_id, None)


# ===========================================================
# Content matching
# ===========================================================


def is_content_match(
    output_words: List[str],
    input_words: List[str],
) -> tuple[bool, str, int, float]:
    """
    Determine if output content matches input content.

    Returns:
        Tuple of (is_match, match_type, match_len, coverage_product)
        - is_match: True if criteria met
        - match_type: "absolute" or "coverage" or ""
        - match_len: Length of longest contiguous match
        - coverage_product: output_coverage * input_coverage
    """
    match_len = compute_longest_match(output_words, input_words)

    # Criterion 1: Absolute match length
    # if match_len >= MIN_MATCH_WORDS:
    #     coverage = (match_len / len(output_words)) * (match_len / len(input_words))
    #     return True, "absolute", match_len, coverage

    # Criterion 2: Coverage-based match
    if match_len > 0 and len(output_words) > 0 and len(input_words) > 0:
        output_coverage = match_len / len(output_words)
        input_coverage = match_len / len(input_words)
        coverage_product = output_coverage * input_coverage
        # if coverage_product >= MIN_COVERAGE_PRODUCT:
        #     return True, "coverage", match_len, coverage_product
        if output_coverage > 0.5 and match_len > MIN_MATCH_WORDS:
            return True, "coverage", match_len, coverage_product

    return False, "", match_len, 0.0


def find_source_nodes(
    session_id: str,
    input_dict: Dict[str, Any],
    api_type: str,
) -> List[str]:
    """
    Find source node IDs whose outputs appear in the given input.

    Uses longest contiguous word match. An edge is created if either:
    1. match_len >= MIN_MATCH_WORDS (absolute threshold), or
    2. output_coverage * input_coverage >= MIN_COVERAGE_PRODUCT (relative threshold)

    Args:
        session_id: The session to search within
        input_dict: The input dictionary for the LLM call
        api_type: The API type identifier (e.g., "httpx.Client.send")

    Returns:
        List of node_ids that should have edges to the new node
    """
    # Extract and tokenize input text
    input_text = extract_input_text(input_dict, api_type)
    if not input_text:
        return []

    input_words = tokenize(input_text)
    if not input_words:
        return []

    logger.debug(f"[string_matching] input has {len(input_words)} words: {input_words[:10]}...")

    # Find matches — snapshot under lock, then match outside it
    with _session_lock:
        session_outputs = dict(_get_session_outputs(session_id))
    matches = []

    for node_id, output_word_lists in session_outputs.items():
        for output_words in output_word_lists:
            is_match, match_type, match_len, coverage = is_content_match(output_words, input_words)
            if is_match:
                logger.info(
                    f"[string_matching] MATCH ({match_type}): node={node_id[:8]}, "
                    f"match={match_len} words, coverage={coverage:.3f}"
                )
                matches.append(node_id)
                break  # Only add node once even if multiple outputs match

    get_graph_topology(session_id=session_id)

    return matches


def store_input_strings(
    session_id: str,
    node_id: str,
    input_dict: Dict[str, Any],
    api_type: str,
) -> None:
    """
    Store input strings from an LLM call for future containment checks.

    Args:
        session_id: The session this input belongs to
        node_id: The node ID that received this input
        input_dict: The input dictionary for the LLM call
        api_type: The API type identifier
    """
    input_text = extract_input_text(input_dict, api_type)
    if not input_text:
        return

    input_words = tokenize(input_text)
    if input_words:
        with _session_lock:
            session_inputs = _get_session_inputs(session_id)
            session_inputs[node_id] = input_words


def store_output_strings(
    session_id: str,
    node_id: str,
    output_obj: Any,
    api_type: str,
) -> None:
    """
    Store output strings from an LLM call for future matching.

    Tokenizes output text for efficient matching.

    Args:
        session_id: The session this output belongs to
        node_id: The node ID that produced this output
        output_obj: The output object from the LLM call
        api_type: The API type identifier
    """
    # Extract output strings
    output_strings = extract_output_text(output_obj, api_type)
    if not output_strings:
        return

    # Split HTML content into separate chunks, then tokenize each
    word_lists = []

    for output_str in output_strings:
        # Split HTML into separate content chunks (each becomes its own word list)
        chunks = split_html_content(output_str)
        for chunk in chunks:
            words = tokenize(chunk)
            if words:
                word_lists.append(words)
                logger.debug(
                    f"[string_matching] stored output: {len(words)} words, " f"node={node_id[:8]}"
                )

    if word_lists:
        with _session_lock:
            session_outputs = _get_session_outputs(session_id)
            session_outputs[node_id] = word_lists


def output_contained_in_input(session_id: str, node_a_id: str, node_b_id: str) -> bool:
    """
    We have A -> B -> C
            A ------> C

    We need to check if the output of A is subset of input to B. If so,
    we don't need A -> C.
    
    Args:
        session_id: The session to search within
        output_node_id: The node whose output might be contained
        input_node_id: The node whose input might contain the output

    Returns:
        True if output_node's output is contained in input_node's input
    """
    with _session_lock:
        output_a = _get_session_outputs(session_id).get(node_a_id, [])
        input_b = _get_session_inputs(session_id).get(node_b_id, [])

    if not output_a or not input_b:
        return False

    total_match_len = sum(compute_longest_match(out_a, input_b) for out_a in output_a)
    total_output_len = sum(len(out_a) for out_a in output_a)
    coverage = total_match_len / total_output_len
    if total_output_len > 0 and coverage >= 0.9:
        return True
    return False
