# API Reference

This section provides auto-generated API documentation from the Sovara source code.

## Overview

Sovara's Python API is organized into several modules:

### CLI Modules

- [**CLI**](cli.md) - Command-line interface entry points (`so-record`, `so-server`, `so-config`)

## Module Structure

```
sovara/
├── cli/                    # Command-line tools
│   ├── so_record.py       # Main launch command
│   ├── so_server.py       # Server management
│   └── so_config.py       # Configuration tool
├── runner/                 # Runtime execution
│   ├── string_matching.py  # Content-based edge detection
│   ├── context_manager.py  # Run management
│   └── monkey_patching/    # API interception
└── server/                 # Core server
    ├── app.py             # FastAPI app factory
    ├── database_manager.py # Caching and content registry
    └── state.py           # Run state and git versioning
```

## Using the API

Most users interact with Sovara through the CLI commands. However, you can also use the Python API directly:

### Context Manager for Subruns

```python
from sovara import launch

with launch("my-run"):
    # Your LLM code here
    pass
```

## Next Steps

- [CLI Reference](cli.md)
