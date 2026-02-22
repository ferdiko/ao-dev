# API Patching

AO uses monkey patching to intercept LLM API calls and record their inputs/outputs for building dataflow graphs.

## Overview

When you import an LLM SDK (like OpenAI or Anthropic), AO patches the relevant methods to:

1. Record the call inputs
2. Execute the original API call
3. Record the outputs
4. Detect dataflow edges using content-based matching
5. Report the call to the server

## Supported APIs

AO intercepts LLM calls via HTTP library patches:

| Patch | Covers |
|-------|--------|
| `httpx_patch.py` | OpenAI, Anthropic (via httpx) |
| `requests_patch.py` | APIs using requests library |
| `genai_patch.py` | Google GenAI |
| `mcp_patches.py` | MCP tool calls |
| `randomness_patch.py` | numpy, torch, uuid seeding |

## How Patches Are Applied

Patches are applied lazily when you import the relevant module. The `PATCHES` dict in `apply_monkey_patches.py` maps module names to patch functions:

```python
PATCHES = {
    "httpx": ("ao.runner.monkey_patching.patches.httpx_patch", "httpx_patch"),
    "requests": ("ao.runner.monkey_patching.patches.requests_patch", "requests_patch"),
    "google.genai": ("ao.runner.monkey_patching.patches.genai_patch", "genai_patch"),
    "mcp": ("ao.runner.monkey_patching.patches.mcp_patches", "mcp_patch"),
    ...
}
```

When you `import httpx`, AO's import hook triggers `httpx_patch()` before returning the module.

## Patch Structure

A typical patch follows this pattern (see `httpx_patch.py` for a complete example):

```python
from ao.runner.string_matching import find_source_nodes, store_output_strings
from ao.runner.context_manager import get_session_id

def patched_function(self, *args, **kwargs):
    api_type = "my_api.method"

    # 1. Build input dict from args/kwargs
    input_dict = get_input_dict(original_function, *args, **kwargs)

    # 2. Find edges using content-based matching (BEFORE cache lookup)
    session_id = get_session_id()
    source_node_ids = find_source_nodes(session_id, input_dict, api_type)

    # 3. Check cache or call the LLM
    cache_output = DB.get_in_out(input_dict, api_type)
    if cache_output.output is None:
        result = original_function(**cache_output.input_dict)
        DB.cache_output(cache_result=cache_output, output_obj=result, api_type=api_type)

    # 4. Store output strings for future matching
    store_output_strings(cache_output.session_id, cache_output.node_id, cache_output.output, api_type)

    # 5. Report node and edges to server
    send_graph_node_and_edges(
        node_id=cache_output.node_id,
        input_dict=cache_output.input_dict,
        output_obj=cache_output.output,
        source_node_ids=source_node_ids,
        api_type=api_type,
    )

    return cache_output.output
```

## Content-Based Edge Detection

AO detects dataflow between LLM calls using content-based matching:

1. **Store outputs**: When an LLM call completes, all text strings from the response are stored
2. **Match inputs**: When a new LLM call is made, we check if any stored output strings appear in the input
3. **Create edges**: If a match is found, an edge is created from the source node to the current node

This approach is simple and robust - user code runs completely unmodified, and edges are detected automatically.

## Writing New Patches

### Step 1: Identify the Target

Determine which method you need to patch. For example:

```
# We want to patch:
client.chat.completions.create(...)
```

### Step 2: Create the Patch File

Add a new file in `src/runner/monkey_patching/patches/`:

```python
# src/runner/monkey_patching/patches/my_api_patch.py

from functools import wraps
from ao.runner.monkey_patching.patching_utils import get_input_dict, send_graph_node_and_edges
from ao.runner.string_matching import find_source_nodes, store_output_strings
from ao.server.database_manager import DB

def patch_my_api_send(original_send):
    @wraps(original_send)
    def patched_send(self, *args, **kwargs):
        # Your patching logic here (see httpx_patch.py for full example)
        pass
    return patched_send
```

### Step 3: Create the Patch Function

In your patch file, create a function that applies the patches when called:

```python
def my_api_patch():
    try:
        from my_api import Client
    except ImportError:
        logger.info("my_api not installed, skipping patches")
        return

    def create_patched_init(original_init):
        @wraps(original_init)
        def patched_init(self, *args, **kwargs):
            original_init(self, *args, **kwargs)
            # Apply method patches here
            patch_my_api_send(self, type(self))
        return patched_init

    Client.__init__ = create_patched_init(Client.__init__)
```

### Step 4: Register in PATCHES

Add your patch to the `PATCHES` dict in `apply_monkey_patches.py`:

```python
PATCHES = {
    "httpx": ("ao.runner.monkey_patching.patches.httpx_patch", "httpx_patch"),
    "my_api": ("ao.runner.monkey_patching.patches.my_api_patch", "my_api_patch"),  # Add here
    ...
}
```

The patch will be applied automatically when users `import my_api`.

## Example: httpx Patch

Here's a simplified view of how the httpx patch works (used by OpenAI, Anthropic, etc.):

```python
def patch_httpx_send(bound_obj, bound_cls):
    original_function = bound_obj.send

    @wraps(original_function)
    def patched_function(self, *args, **kwargs):
        api_type = "httpx.Client.send"
        input_dict = get_input_dict(original_function, *args, **kwargs)

        # Check if URL is whitelisted (LLM endpoint)
        request = input_dict["request"]
        if not is_whitelisted_endpoint(str(request.url), request.url.path):
            return original_function(*args, **kwargs)

        # Get cached result or call LLM
        cache_output = DB.get_in_out(input_dict, api_type)
        if cache_output.output is None:
            result = original_function(**cache_output.input_dict)
            DB.cache_output(cache_result=cache_output, output_obj=result, api_type=api_type)

        # Content-based edge detection
        source_node_ids = find_source_nodes(cache_output.session_id, cache_output.input_dict, api_type)
        store_output_strings(cache_output.session_id, cache_output.node_id, cache_output.output, api_type)

        # Report to server
        send_graph_node_and_edges(...)
        return cache_output.output

    bound_obj.send = patched_function.__get__(bound_obj, bound_cls)
```

## Async Support

Many LLM APIs are async. Patches must handle both sync and async methods:

```python
def patch_method(original):
    if asyncio.iscoroutinefunction(original):
        @wraps(original)
        async def async_patched(*args, **kwargs):
            # async implementation
            pass
        return async_patched
    else:
        @wraps(original)
        def sync_patched(*args, **kwargs):
            # sync implementation
            pass
        return sync_patched
```

## API Parsers

Each LLM API has different request/response formats. API parsers extract relevant information:

```
src/runner/monkey_patching/api_parsers/
├── httpx_api_parser.py    # OpenAI, Anthropic (via httpx)
├── requests_api_parser.py # APIs using requests
├── genai_api_parser.py    # Google GenAI
└── mcp_api_parser.py      # MCP tool calls
```

Parsers normalize HTTP responses into a common format for caching and display. See `api_parser.py` for the main interface that routes to the appropriate parser based on `api_type`.

## Maintenance

LLM APIs change frequently. To detect API changes:

1. Run tests after upgrading SDK versions
2. Check for deprecation warnings
3. Review SDK changelogs

## Next Steps

- [Edge Detection](edge-detection.md) - How dataflow edges are detected
- [Testing](testing.md) - Running the test suite
- [Architecture](architecture.md) - System overview
