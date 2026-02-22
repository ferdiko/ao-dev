# Edge Detection

AO detects dataflow between LLM calls using content-based matching. This document explains how edges are created in the dataflow graph.

## Overview

The edge detection system answers: "Which LLM outputs were used as input to this LLM call?"

When an LLM produces output, we store all text strings from the response. When a new LLM call is made, we check if any previously stored strings appear in the input. If so, we create an edge between those nodes.

## Core Architecture

### Content Registry

The content registry lives in `string_matching.py` and stores tokenized output strings for each node:

```python
# Maps session_id -> {node_id -> [[word_lists]]}
_session_outputs: Dict[str, Dict[str, List[List[str]]]] = {}
```

Key properties:
1. **Session-scoped:** Outputs are only matched within the same session
2. **In-memory:** No persistence needed (LLM outputs are already cached in the database)
3. **Tokenized:** Text is split into words for efficient longest-match computation

### String Matching Module

The matching logic is in `src/runner/string_matching.py`:

```python
find_source_nodes(session_id, input_dict, api_type) -> List[str]
    # Returns node_ids whose outputs appear in this input

store_output_strings(session_id, node_id, output_obj, api_type) -> None
    # Stores output strings for future matching
```

### Text Extraction

Text is extracted from HTTP request/response bodies in `patching_utils.py`:

- `extract_input_text(input_dict, api_type)` - Extracts all strings from the request body
- `extract_output_text(output_obj, api_type)` - Extracts all strings from the response body

Both functions recursively extract all string values from the JSON, regardless of the API format (OpenAI, Anthropic, etc.).

## How It Works

### Example Flow

```python
# LLM call 1
response1 = llm("Output the number 42")  # Returns "42"
# -> Stored: node_1 -> ["42", "assistant", "stop", ...]

# LLM call 2
response2 = llm(f"Add 1 to {response1}")  # Input contains "42"
# -> Input text: "Add 1 to 42..."
# -> Match found: "42" in input
# -> Edge created: node_1 -> node_2
```

### Matching Algorithm

Uses word-level longest contiguous match via `difflib.SequenceMatcher`:

```python
def is_content_match(output_words, input_words):
    match_len = compute_longest_match(output_words, input_words)
    if match_len > 0 and len(output_words) > 0:
        output_coverage = match_len / len(output_words)
        if output_coverage > 0.5 and match_len > MIN_MATCH_WORDS:
            return True
    return False
```

Key features:
- **Tokenization:** Text is cleaned (HTML stripped, lowercased) and split into words
- **Coverage threshold:** Match must cover >50% of the output
- **Minimum length:** Match must exceed `MIN_MATCH_WORDS` (default: 3)

## Integration with Monkey Patches

Each monkey patch (httpx, requests, MCP, genai) calls the string matching functions:

```python
# In httpx_patch.py
source_node_ids = find_source_nodes(session_id, input_dict, api_type)
store_output_strings(session_id, node_id, output, api_type)

send_graph_node_and_edges(
    node_id=node_id,
    source_node_ids=source_node_ids,  # Edges!
    ...
)
```

## Caching and Reruns

When an LLM call is intercepted:

1. **Cache lookup**: `DB.get_in_out()` hashes the input
2. **Cache hit**: Use cached output
3. **Cache miss**: Call LLM, store result
4. **Edge detection**: `find_source_nodes()` checks for matches
5. **Store output**: `store_output_strings()` saves for future matching
6. **Graph update**: `send_graph_node_and_edges()` notifies server

**Reruns work deterministically** because:
- Same `session_id` means cache lookups find previous entries
- Content registry is rebuilt as calls are replayed
- UI edits to inputs/outputs are respected

## Next Steps

- [API patching](api-patching.md) - How LLM APIs are intercepted
- [Testing](testing.md) - Running the test suite
