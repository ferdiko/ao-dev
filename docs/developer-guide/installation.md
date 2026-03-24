# Installation (Development)

This guide covers how to install Sovara from source for development purposes.

## Prerequisites

- Python 3.10 or higher
- Node.js 22 or higher (for VS Code extension development)
- Git

## Option 1: Using uv (Recommended)

[uv](https://docs.astral.sh/uv/) is a fast Python package installer that simplifies dependency management.

### Install uv

```bash
# macOS/Linux
curl -LsSf https://astral.sh/uv/install.sh | sh

# Or with Homebrew
brew install uv
```

### Clone and Install

```bash
git clone https://github.com/SovaraLabs/sovara.git
cd sovara

# Install with all development dependencies
uv sync --extra dev --extra docs
```

This installs:

- `dev` - Testing tools (pytest), linting (black, pre-commit), and provider SDKs
- `docs` - Documentation tools (mkdocs-material)

### Running Commands

With uv, use `uv run` to execute commands in the project environment:

```bash
# Run the server
uv run so-server start

# Record a script
uv run so-record script.py

# Run tests
uv run pytest

# Build documentation
uv run mkdocs serve
```

## Option 2: Using Conda + pip

Traditional installation using conda for environment management and pip for package installation.

### Create Environment

```bash
# Create and activate conda environment
conda create -n sovara python=3.13 -y
conda activate sovara

# Clone the repository
git clone https://github.com/SovaraLabs/sovara.git
cd sovara

# Install in development mode with all extras
pip install -e ".[dev,docs]"
```

### Running Commands

With conda, activate the environment first:

```bash
conda activate sovara

# Run the server
so-server start

# Record a script
so-record script.py

# Run tests
pytest

# Build documentation
mkdocs serve
```

## VS Code Extension Development

The VS Code extension requires additional setup:

```bash
cd ui/vscode_extension

# Install npm dependencies
npm install

# Build the extension
npm run compile

# Or watch for changes during development
npm run watch
```

To test the extension, press `F5` in VS Code with the extension folder open, or use the "Run Extension" launch configuration.

## Verifying Installation

After installation, verify everything works:

```bash
# Check CLI tools are available
so-server --help
so-record --help

# Start the server
so-server start

# Check server logs
so-server logs

# Run a simple test
uv run pytest tests/non_billable/ -v --tb=short
```

## Next Steps

- [Architecture](architecture.md) - Understand the system design
- [Testing](testing.md) - Run and write tests
- [API Patching](api-patching.md) - Add support for new LLM APIs
