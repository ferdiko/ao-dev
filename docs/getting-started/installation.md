# Installation

## Prerequisites

- Python 3.10 or higher (Python 3.13 recommended)
- Node.js (for building the VS Code extension)

## Quick Install (pip)

```bash
pip install sovara
```

## Quick Install (uv)

If you use [uv](https://docs.astral.sh/uv/) for package management, add `sovara` to your project's dependencies:

```bash
uv add sovara
```

Then run your scripts with:

```bash
uv run so-record script.py
```

## Verifying Installation

After installation, verify that the CLI commands are available:

```bash
so-record --help
so-server --help
```

## Building from Source

### Create Environment

If you're starting from a clean sheet, create a conda environment with the required dependencies:

```bash
conda create -n sovara python=3.13 nodejs sqlite -y && conda activate sovara
```

### Install and Build

For non-developers, install the project and build the UI:

```bash
pip install -e .
cd ui && npm run install:all && npm run build:extension
```

### Running the Extension

Open this project in a new VS Code window. Select the "Run Extension" option from the debugger and run it. This will open a new window with the extension enabled.

![Launch extension](../media/launch_extension.gif)

### Try an Example

In the new window, you can now open any project that you are working on. For example, run the `openai_debate.py` example from the `example_workflows/debug_examples/` folder:

```bash
so-record ./example_workflows/debug_examples/openai_debate.py
```

> **Note:** This example depends on the OpenAI API. You may need to install it first: `pip install openai`

![Run example](../media/run_example.gif)

## Developer Installation

If you are contributing to Sovara, install with development dependencies and set up pre-commit hooks:

```bash
pip install -e ".[dev]"
pre-commit install
cd ui && npm run install:all && npm run build:extension
```

## Next Steps

- [Run your first example](quickstart.md)
- [Learn the CLI commands](../user-guide/cli-commands.md)
