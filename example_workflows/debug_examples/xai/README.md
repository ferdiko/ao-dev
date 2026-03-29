# xAI Grok Debug Example

This folder contains a small `so-record` example that uses the OpenAI Python client against xAI's OpenAI-compatible API.

## API key setup

Export your xAI API key before running the example:

```bash
export XAI_API_KEY=your_xai_api_key
```

## Run it

```bash
cd example_workflows/debug_examples/xai
uv run so-record debate.py
```

The script uses `grok-4-fast-non-reasoning` by default so the traced nodes exercise the new Grok display alias handling.
