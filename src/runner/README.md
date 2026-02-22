# Running a user script

When the user runs `ao-record script.py` (instead of `python script.py`), they create an AgentRunner instance that runs their script.


## agent_runner.py

This is the wrapper around the user's python command. It works like this:

1. **Set up environment**: Sets random seed for reproducibility.
2. **Connect to server**: Connects to the main server. If it isn't running already, it starts it.
3. **Listen for messages**: Starts a thread to listen to `kill` messages from the server (if the user kills/reruns before the user program finished).
4. **Send restart command**: The "rerun command" is used by the server to issue the same command the user issued to trigger the current run. It also transmits working dir, env vars, etc. We send it async because it takes long to generate the command and don't want it to be on the critical path.
5. **Run user program**: Starts the user program unmodified.

## context_manager.py

Manages context like the session ids for different threads.

Sometimes the user wants to do "subruns" within their `ao-record` run. For example, if the user runs an eval script, they may want each sample to be a separate run. They can do this as follows:

```
for sample in samples:
    with ao_launch("run name"):
        eval_sample(prompt)
```

This can also be used to run many samples concurrently (see examples in `example_workflows/debug_examples/`).

## string_matching.py

Implements content-based edge detection. When an LLM call is made, we check if any previous LLM outputs appear in the current input. If so, we create an edge between those nodes.

This module provides:
- `find_source_nodes(session_id, input_dict, api_type)` - Find which previous outputs appear in this input
- `store_output_strings(session_id, node_id, output_obj, api_type)` - Store output strings for future matching

## Computing data flow (graph edges)

We detect dataflow between LLM calls using **content-based matching**:

1. **Record LLM outputs**: When an LLM call completes, we extract all text strings from the response and store them.

2. **Match on input**: When a new LLM call is made, we extract all text from the input and check if any previously stored output strings appear as substrings.

3. **Create edges**: If a match is found, we create an edge from the source node (whose output matched) to the current node.

This approach is simple and robust:
- User code runs completely unmodified
- Works with any LLM library that uses httpx/requests under the hood
- No risk of crashing user code

The matching algorithm is implemented in [string_matching.py](/src/runner/string_matching.py).

## Intercepting LLM call events (graph nodes)

We write monkey patches at a level as low as possible. I.e., we try to not patch `openai` but `httpx`, the http package that `openai`, `anthropic` and others use so one patch serves many libraries.

## Caching and Reruns

When an LLM call is intercepted (e.g., in [httpx_patch.py](/src/runner/monkey_patching/patches/httpx_patch.py)), the following happens:

1. **Cache lookup**: `DB.get_in_out()` hashes the input and looks it up by `(session_id, input_hash)`. The [database_manager.py](/src/server/database_manager.py) handles all cache operations.

2. **Cache hit**: If a matching entry exists:
   - If `input_overwrite` is set (user edited input in UI), use the modified input instead
   - If `output` is cached (from previous run or user-edited), return it directly without calling the LLM

3. **Cache miss**: If no entry exists or output is `None`:
   - Call the actual LLM with the (possibly overwritten) input
   - Store the result via `DB.cache_output()` for future runs

4. **Edge detection**: `find_source_nodes()` checks if any previous outputs appear in this input.

5. **Graph update**: `send_graph_node_and_edges()` notifies the server to update the UI with the node and its edges.

**Reruns work deterministically** because:
- The same `session_id` (inherited from parent) means cache lookups find previous entries
- Cached outputs are returned without re-calling the LLM
- Users can modify inputs/outputs via the UI, and these overwrites are respected on rerun
- Randomness is patched (random, numpy, torch) to produce the same sequence given the same seed

This enables interactive debugging: run once, inspect the graph, edit an LLM's input or output, and rerun to see how changes propagate through the dataflow.
