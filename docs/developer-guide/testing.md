# Testing

This guide covers how to run AO's test suite and write new tests.

## Running Tests

### With uv (Recommended)

If you installed with uv, run tests using `uv run`:

```bash
# Run all non-billable tests
uv run pytest tests/non_billable/ -v

# Run specific test file
uv run pytest tests/non_billable/test_string_matching.py -v

# Run tests matching a pattern
uv run pytest -k "test_edge" -v

# Run with full output
uv run pytest -v -s tests/non_billable/
```

### With Conda/pip

If you installed with conda, activate the environment first:

```bash
conda activate ao

# Run all non-billable tests
pytest tests/non_billable/ -v

# Run specific test file
pytest tests/non_billable/test_string_matching.py -v

# Run tests matching a pattern
pytest -k "test_edge" -v
```

## Test Categories

### Non-Billable Tests

Tests that don't make real API calls. These are safe to run frequently:

```bash
uv run pytest tests/non_billable/ -v
```

Includes:

- **String matching tests** - Verify content-based edge detection works correctly
- **Unit tests** - Test individual components in isolation

### Billable Tests

Tests that make real LLM API calls. These cost money and should be run sparingly:

```bash
# Run a single billable test (requires API keys)
uv run pytest -v -s "tests/billable/test_caching.py::test_debug_examples[./example_workflows/debug_examples/anthropic/debate.py]"

# Run all billable tests (expensive!)
uv run pytest tests/billable/ -v -s
```

!!! warning "API Keys Required"
    Billable tests require environment variables for API keys:
    `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `TOGETHER_API_KEY`, etc.

!!! note "Quoting in zsh"
    If using zsh, quote test paths with brackets to prevent shell expansion:
    ```bash
    uv run pytest "tests/billable/test_caching.py::test_debug_examples[./example_workflows/debug_examples/anthropic/debate.py]"
    ```

## Edge Detection Tests

Tests for content-based edge detection verify that dataflow edges are correctly detected when LLM outputs appear in subsequent LLM inputs:

```bash
uv run pytest -v tests/non_billable/test_string_matching.py
python -m pytest tests/billable/ -k "edge"
```

## Writing New Tests

### Adding a New Billable Test Case

Billable tests run example scripts that make real LLM API calls. Each provider has its own folder with a `pyproject.toml` and `uv.lock` for isolated dependencies.

**1. Create or navigate to the provider folder:**

```
example_workflows/debug_examples/<provider>/
```

Existing providers: `anthropic`, `openai`, `langchain`, `together`, `google`, `mcp`, `subruns`

**2. Add your test script:**

```python
# example_workflows/debug_examples/openai/my_new_test.py
from openai import OpenAI

client = OpenAI()
response = client.chat.completions.create(
    model="gpt-4o-mini",
    messages=[{"role": "user", "content": "Hello!"}]
)
print(response.choices[0].message.content)
```

**3. If adding a new provider, create the folder structure:**

```bash
mkdir -p example_workflows/debug_examples/newprovider
```

Create `pyproject.toml`:

```toml
[project]
name = "ao-examples-newprovider"
version = "0.1.0"
description = "AO debug examples for NewProvider"
requires-python = ">=3.10"
dependencies = [
    "ao-dev",
    "newprovider-sdk",  # The provider's SDK
]

[tool.uv.sources]
ao-dev = { path = "../../..", editable = true }
```

Generate `uv.lock`:

```bash
cd example_workflows/debug_examples/newprovider
uv sync
```

This creates `uv.lock` which should be committed to the repository for reproducible CI builds.

**4. Add the test case to `test_caching.py`:**

```python
@pytest.mark.parametrize(
    "script_path",
    [
        # ... existing tests ...
        "./example_workflows/debug_examples/newprovider/my_new_test.py",
    ],
)
def test_debug_examples(script_path: str):
    run_data_obj = asyncio.run(run_test(script_path=script_path))
    caching_asserts(run_data_obj)
```

**5. Run your test locally:**

```bash
uv run pytest -v -s "tests/billable/test_caching.py::test_debug_examples[./example_workflows/debug_examples/newprovider/my_new_test.py]"
```

### Standard Test

```python
# tests/non_billable/test_my_feature.py
import pytest

def test_my_feature():
    # Your test code
    assert result == expected
```

### Edge Detection Test

To test that edges are correctly detected:

```python
def test_edge_detection():
    # LLM call 1 - output contains "42"
    response1 = llm_call("Output the number 42")

    # LLM call 2 - input contains "42" from previous output
    response2 = llm_call(f"Add 1 to {response1}")

    # Verify an edge was created between the two nodes
    # Check the graph topology in the session
    pass
```

## Test Fixtures

Common test helpers are defined in `tests/utils.py`, including:

```python
@pytest.fixture
def server_connection():
    # Setup server connection for integration tests
    pass
```

## Debugging Failed Tests

### View Server Logs

```bash
ao-server logs
```

### Run with Debug Output

```bash
uv run pytest -v --tb=long tests/non_billable/test_failing.py
```

### Run Single Test

```bash
uv run pytest -v "tests/non_billable/test_file.py::test_specific_function"
```

### API Call Tests

For API call tests, the user program executes as a replay by the server. To see the output:

```bash
ao-server logs
```

This shows the output of the user program, including any crash information.

## CI/CD

### Running Tests Locally Before Push

```bash
# Run all non-billable tests
uv run pytest tests/non_billable/ -v

# Run with coverage
uv run pytest tests/non_billable/ --cov=ao --cov-report=html
```

### Billable Tests in CI

Billable tests run in GitHub Actions when triggered by a `/run-billable-tests` comment on a PR. They require:

- Write permission on the repository
- Configured API key secrets

Key considerations:

- Tests must be deterministic (use fixed random seeds)
- API tests should use mocks or replay mode when possible
- Edge detection tests require the full `ao-record` environment

## Next Steps

- [Architecture](architecture.md) - Understand the system design
- [API Patching](api-patching.md) - Write patches for new LLM APIs
