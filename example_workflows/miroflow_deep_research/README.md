# Imitation of DeepResearch based on MiroFlow

## Dependencies
First, init the submodule:
```bash
git submodule update --init
```
This should have cloned [MiroFlow](https://github.com/MiroMindAI/MiroFlow) into this directory.
```bash
pip install -e MiroFlow/libs/miroflow-contrib
pip install -e MiroFlow/libs/miroflow-tool
pip install -e MiroFlow/libs/miroflow
```

In this example folder, there is a [.env.template](.env.template). Copy this file and rename it to `.env`. Now, fill in the missing API keys.
When executing the script, the `.env` file will be read, and the API keys inside will be used. Don't worry, the `.env` file is not synced.

## Configs
The folder [configs/](./config/) controls the settings of the agent. This includes which model will be used and what tools are available.

## Running a simple task
Try to run
```bash
so-record ./example_workflows/miroflow_deep_research/single_task.py
```