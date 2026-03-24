# Building from source and developing

See the READMEs in `src/sovara/` and [ui/README.md](/Users/jub/ao-dev/ui/README.md) for more details.

## User workflow (Python semantics)
We assume the user coded their workflow in Python, i.e., it can be run with something like:

 - `python -m foo.bar`
 - `ENV_VAR=5 python script.py --some-flag`

All they change is the Python command. Whenever they want to record their agent's trajectory graph, they run:

 - `so-record -m foo.bar`
 - `ENV_VAR=5 so-record script.py --some-flag`

This will feel *exactly* the same as running Python. The program prints to and reads from the same terminal, crashes the same way, etc.

A core goal of development is to provide this illusion while recording the agent's traectory graph.

## Building from source

### Installation

If you're starting from a clean sheet, create a blank conda environment and activate it. We recommend Python 3.13, but Python all versions >=3.10 are supported.
```bash
conda create -n sovara python=3.13 nodejs sqlite -y && conda activate sovara
```

> [!NOTE]  
> If you are a developer of this project, jump to the [Development](#development) section for installation instructions.

For non-developers, install the project like so (install python deps and build UI):
```bash
pip install -e .
cd ui && npm run install:all && npm run build:extension
```

### Running the extension
Open this project in a new VS Code window. Select the "Run Extension" option from the debugger and run it. This will open a new window with the extension enabled (see the video below):

![Launch extension](/docs/media/launch_extension.gif)


### Try an example
In the new window, you can now open any project that you are working on. We will run the `openai_debate.py` example from our [examples](/example_workflows/debug_examples/) folder. Note that this example depends on the OpenAI API, which you might need to install before running the example (`pip install openai`).

If you run the following command, you should see the result in the video:
```bash
so-record ./example_workflows/debug_examples/openai_debate.py
```

![Run example](/docs/media/run_example.gif)

## Development

Please install the project as follows (install python dev deps, pre-commit hook for code formatting and build UI):
```bash
pip install -e ".[dev]"
pre-commit install
cd ui && npm run install:all && npm run build:extension
```

### Architecture

Our code base is structured into the following components:

1. Run user program (green): The users launch processes of their program by running `so-record their_script.py` which feels exactly like running their script normally with `python their_script.py`. Under the hood the `so-record` command installs monkey patches to intercept LLM calls and log them to the `main server`. Dataflow between LLM calls is detected using content-based matching: we check if previous LLM outputs appear as substrings in new LLM inputs. User code runs completely unmodified. [Code](/src/sovara/runner/)
2. Develop server (blue): The `main server` is the core of the system and responsbible for all analysis. It receives the logs from the user process and updates the UI according to its analyses. All communication to/from the `main server` happens over one TCP socket (default: 5959). [Code](/src/sovara/server/)
3. UI (red): We currently implement the UI as VS Code extension and web app, where most webview components between the two are shared. The UI gets updated by the `main server`. [Code](/ui/)

![Processes overview](/docs/media/processes.png)


### Server commands and log

Upon running `so-record` or actions in the UI, the server will be started automatically. It will also automatically shut down after periods of inactivity. Use the following to manually start and stop the server:

 - `so-server start`
 - `so-server stop`
 - `so-server restart`
 
> [!NOTE]
> When you make changes to the server code, you need to restart such that these changes are reflected in the running server!

If you want to clear all recorded runs and cached LLM calls (i.e., clear the DB), do `so-server clear`.

Git versioning for user files is coordinated in [state.py](/Users/jub/ao-dev/src/sovara/server/state.py) so runs can be tied to code snapshots. To see logs, use these commands:

 - Logs of the main server: `so-server logs`
 - Clear the log file before a fresh restart: `so-server clear-logs`

Note that all server logs are printed to files and not visible from any terminal.

## Tests

Our CI test suit comprises of ["non_billable"](/tests/non_billable) and ["billable"](/tests/billable) tests. Billable tests use third-party APIs and therefore incur costs. You should run both of these tests locally to make sure your code works as expected. In our CI/CD, we run non-billable tests on every commit and, before a PR is merged, an repo maintainer will also run the billable tests on it. To do so, leave a comment on the PR containing "/run-billable-tests". After the tests run, github-actions will leave a comment whether the tests passed or failed.

## Releasing

### PyPI package

Use `uv` as the default workflow. The equivalent `pip` / `python -m ...` commands are included below for reference.

1. ‼️ Check `pyproject.toml`: confirm version number, package name, dependencies, and anything else that is relevant.
2. Export the package version into your shell so the later commands can reuse it:

```bash
# run from sovara/
export VERSION="$(sed -n 's/^version = "\(.*\)"/\1/p' pyproject.toml)"
```

3. ‼️ Check the PyPI description at [/docs/release/PYPI_DESC.md](/docs/release/PYPI_DESC.md).
4. ‼️ Set the `logger` level (not `server_logger`) to `CRITICAL` [here](/src/sovara/common/logger.py). The `server_logger` can stay at `DEBUG`.
5. Install build/upload tooling if needed.

```bash
# uv way
uv tool install twine

# pip way
pip install build twine
```

6. Build the package in the repo root. This creates `dist/`.

```bash
# uv way
uv build

# pip way
python -m build
```

7. Test-install the built wheel locally into a clean test venv. The wheel should match `dist/sovara-${VERSION}-*.whl`.

```bash
# uv way
uv venv .venv-test
uv pip install --python .venv-test/bin/python dist/sovara-${VERSION}-*.whl

# pip way
python -m venv .venv-test
.venv-test/bin/pip install dist/sovara-${VERSION}-*.whl
```

8. Test the installed package by recording the OpenAI debate example with `so-record`. This validates that the installed wheel works, not just the local source tree, and preserves normal interactive terminal behavior.

```bash
uv run --no-project --python .venv-test/bin/python --with openai so-record --run-name "OAI-debate-run-1" example_workflows/debug_examples/openai/debate.py
```

9. Do a test upload first.

```bash
# uv way
uvx twine upload --repository testpypi dist/sovara-${VERSION}*

# pip way
python -m twine upload --repository testpypi dist/sovara-${VERSION}*
```

10. Verify install from TestPyPI.

```bash
# uv way
uv pip install --python .venv-test/bin/python --index-url https://test.pypi.org/simple/ --extra-index-url https://pypi.org/simple/ sovara==$VERSION

# pip way
.venv-test/bin/pip install --index-url https://test.pypi.org/simple/ --extra-index-url https://pypi.org/simple/ sovara==$VERSION
```

11. Upload to PyPI.

```bash
# uv way
uvx twine upload dist/sovara-${VERSION}*

# pip way
python -m twine upload dist/sovara-${VERSION}*
```

12. Make a release on GitHub. This is just to keep track of things; no description is needed. Go to "Releases" and do "Draft new release".


### VS Code extension

- You can change developer settings and look at statistics at https://marketplace.visualstudio.com/manage/.

1. ‼️ Look at  [package.json](../ui/vscode_extension/package.json). Make sure the extension metadata is what you want.
2. ‼️ Look at the [README](../ui/vscode_extension/README.md) for the Marketplace description and [icon](../ui/vscode_extension/icon.png) for the extension icon.
3. Install `@vscode/vsce` globally if you haven't already. You can run this from any directory:
   `npm install -g @vscode/vsce`
4. Create VSIX package: `cd ui/vscode_extension` and run `./build-vsix.sh`.
5. Try to install the VSIX locally to see if it works: Go to the marketplace, click the three dots at the top right of the panel, click "Install from VSIX...".
6. Publish to store: Upload via https://marketplace.visualstudio.com/manage/.

## Further resources

 - [Join our discord server](https://discord.gg/fjsNSa6TAh)
 - [Read our docs](https://docs.sovara-labs.com/)
