# Building from source and developing

See README's in src dirs for more details.

## User workflow (Python semantics)
We assume the user coded their workflow in Python, i.e., it can be run with something like:

 - `python -m foo.bar`
 - `ENV_VAR=5 python script.py --some-flag`

All they change is the Python command. Whenever they want to record their agent's trajectory graph, they run:

 - `ao-record -m foo.bar`
 - `ENV_VAR=5 ao-record script.py --some-flag`

This will feel *exactly* the same as running Python. The program prints to and reads from the same terminal, crashes the same way, etc.

A core goal of development is to provide this illusion while recording the agent's traectory graph.

## Building from source

### Installation

If you're starting from a clean sheet, create a blank conda environment and activate it. We recommend Python 3.13, but Python all versions >=3.10 are supported.
```bash
conda create -n ao python=3.13 nodejs sqlite -y && conda activate ao
```

> [!NOTE]  
> If you are a developer of this project, jump to the [Development](#development) section for installation instructions.

For non-developers, install the project like so (install python deps and build UI):
```bash
pip install -e .
cd src/user_interfaces && npm run install:all && npm run build:extension
```

### Running the extension
Open this project in a new VS Code window. Select the "Run Extension" option from the debugger and run it. This will open a new window with the extension enabled (see the video below):

![Launch extension](/docs/media/launch_extension.gif)


### Try an example
In the new window, you can now open any project that you are working on. We will run the `openai_debate.py` example from our [examples](/example_workflows/debug_examples/) folder. Note that this example depends on the OpenAI API, which you might need to install before running the example (`pip install openai`).

If you run the following command, you should see the result in the video:
```bash
ao-record ./example_workflows/debug_examples/openai_debate.py
```

![Run example](/docs/media/run_example.gif)

## Development

Please install the project as follows (install python dev deps, pre-commit hook for code formatting and build UI):
```bash
pip install -e ".[dev]"
pre-commit install
cd src/user_interfaces && npm run install:all && npm run build:extension
```

Some Python linters will (incorrectly) say that the modules inside our code base can't be found. Run the following in the project root to make these linters happy:

```
ln -s src ao
```

### Architecture

Our code base is structured into the following components:

1. Run user program (green): The users launch processes of their program by running `ao-record their_script.py` which feels exactly like running their script normally with `python their_script.py`. Under the hood the `ao-record` command installs monkey patches to intercept LLM calls and log them to the `main server`. Dataflow between LLM calls is detected using content-based matching: we check if previous LLM outputs appear as substrings in new LLM inputs. User code runs completely unmodified. [Code](/src/runner/)
2. Develop server (blue): The `main server` is the core of the system and responsbible for all analysis. It receives the logs from the user process and updates the UI according to its analyses. All communication to/from the `main server` happens over one TCP socket (default: 5959). [Code](/src/server/)
3. UI (red): We currently implement the UI as VS Code extension and web app, where most webview components between the two are shared. The UI gets updated by the `main server`. [Code](/src/user_interfaces/)

![Processes overview](/docs/media/processes.png)


### Server commands and log

Upon running `ao-record` or actions in the UI, the server will be started automatically. It will also automatically shut down after periods of inactivity. Use the following to manually start and stop the server:

 - `ao-server start`
 - `ao-server stop`
 - `ao-server restart`
 
> [!NOTE]
> When you make changes to the server code, you need to restart such that these changes are reflected in the running server!

If you want to clear all recorded runs and cached LLM calls (i.e., clear the DB), do `ao-server clear`.

The server spawns a [file watcher](/src/server/file_watcher.py) process that handles git versioning of user files, so we can display fine-grained file versions to the user (upon them changing files, not only upon them committing using their own git). To see logs, use these commands:

 - Logs of the main server: `ao-server logs`
 - Logs of the file watcher (git versioning): `ao-server git-logs`

Note that all server logs are printed to files and not visible from any terminal.

## Tests

Our CI test suit comprises of ["non_billable"](/tests/non_billable) and ["billable"](/tests/billable) tests. Billable tests use third-party APIs and therefore incur costs. You should run both of these tests locally to make sure your code works as expected. In our CI/CD, we run non-billable tests on every commit and, before a PR is merged, an repo maintainer will also run the billable tests on it. To do so, leave a comment on the PR containing "/run-billable-tests". After the tests run, github-actions will leave a comment whether the tests passed or failed.

## Releasing

### pip package

1. ‼️ Check `pyproject.toml`: Check version number, package name, dependencies and anything else that's relevant.
2. ‼️ Check the PyPi description at [/docs/release/PYPI_DESC.md](/docs/release/PYPI_DESC.md).
3. ‼️ Set the `logger` level (not `server_logger`) to `CRITICAL` [here](/src/common/logger.py). The server_logger can stay at `DEBUG`.
4. Install `pip install build twine` if you haven't already.
5. Run `python -m build` in root dir. This wil create a `dist/` dir.
6. Test install locally: `pip install dist/ao_dev-0.0.5-py3-none-any.whl` (you need to check the name of the `.whl` file).
7. Do a test upload, it's worth it:
   1. Publish to TestPyPI first: `python -m twine upload --repository testpypi dist/*`. Then try to install from TestPyPi. Ask Ferdi if you don't have the key to our TestPyPI account.
   2. When installing from TestPyPI, do the following (just swap out the package name at the end of the command): `pip install --index-url https://test.pypi.org/simple/ --extra-index-url https://pypi.org/simple/ ao-dev==0.0.1`
8. Upload to PyPI: `python -m twine upload dist/*`. Ask Ferdi if you don't have the key to our PyPI account.
9. Make a release on github: This is just to keep track of things, no need to put any description. Just go to "Releases" and do "Draft new release".


### VS Code extension

- You can change developer settings and look at statistics at https://marketplace.visualstudio.com/manage/. Ask Ferdi if you need a log in.

1. ‼️ Look at `src/user_interfaces/vscode_extension/package.json`. Make sure name, description, version, etc. are what you want. (Don't worry about "icon", see below)
2. ‼️ Look at the marketplace description at [/docs/release/VSIX_DESC.md](/docs/release/VSIX_DESC.md). Also look at the icon at [/docs/release/marketplace_icon.png](/docs/release/marketplace_icon.png)
3. Install `npm install -g @vscode/vsce` if you haven't already.
4. Create VSIX package: `cd src/user_interfaces/vscode_extension` and run `./build-vsix.sh`.
5. Try to install the VSIX locally to see if it works: Go to the marketplace, click the three dots at the top right of the panel, click "Install from VSIX...".
6. Publish to store: Upload via https://marketplace.visualstudio.com/manage/. Ask Ferdi for log-in if you don't have it.

### Hosted web app

> [!NOTE]  
> We stopped hosting the web app.

## Further resources

 - [Join our discord server](https://discord.gg/fjsNSa6TAh)
 - [Read our docs](https://agent-ops-project.github.io/ao-agent-dev/)
