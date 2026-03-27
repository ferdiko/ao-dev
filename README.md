# Sovara: What-if Questions over Agent Trajectories

Sovara is a developer tool for agent builders. It supports arbitrary Python progams (like your existing agents!) and will visualize your agent's LLM and MCP calls into a dataflow graph. You can then inspect, edit and rerun this graph and understand how to fix your agent.

[![Quickstart video](docs/media/quickstart_screenshot.png)](https://youtu.be/woVctiSRJU0)


## Quickstart

`Sovara` integrates into VS Code or IDEs based on it, like Cursor.

Simply download (1) our [VS Code Extension](https://marketplace.visualstudio.com/items?itemName=SovaraLabs.sovara) (type sovara dev into the marketplace search and install the one with the blue icon by "Sovara Labs"), (2) install our pip package:

```bash
pip install sovara
```

Or if you use [uv](https://docs.astral.sh/uv/):

```bash
uv add sovara
```

**Then, give it a spin:**

1. Create some little agent program that you want to run (or use your existing agent!). For example, you can try this little OpenAI example below (or find many further example scripts in our [examples folder](/example_workflows/debug_examples/)):

```python
from openai import OpenAI


def main():
    client = OpenAI()

    # First LLM: Generate a yes/no question
    question_response = client.responses.create(
        model="gpt-4o-mini",
        input="Come up with a simple question where there is a pro and contra opinion. Only output the question and nothing else.",
        temperature=0,
    )
    question = question_response.output_text

    # Second LLM: Argue "yes"
    yes_prompt = f"Consider this question: {question}\nWrite a short paragraph on why to answer this question with 'yes'"
    yes_response = client.responses.create(
        model="gpt-4o-mini", input=yes_prompt, temperature=0
    )

    # Third LLM: Argue "no"
    no_prompt = f"Consider this question: {question}\nWrite a short paragraph on why to answer this question with 'no'"
    no_response = client.responses.create(
        model="gpt-4o-mini", input=no_prompt, temperature=0
    )

    # Fourth LLM: Judge who won
    judge_prompt = f"Consider the following two paragraphs:\n1. {yes_response.output_text}\n2. {no_response.output_text}\nWho won the argument?"
    judge_response = client.responses.create(
        model="gpt-4o-mini", input=judge_prompt, temperature=0
    )

    print(f"Question: {question}")
    print(f"\nJudge's verdict: {judge_response.output_text}")

if __name__ == "__main__":
    main()
```

2. Run the script using `so-record`.

```bash
so-record openai_example.py
```

This should show you the agent's trajectory graph like in the video above. You can edit inputs and outputs in the graph and rerun.

## Integration with Coding Agents
Coding Agents already accelerate generic coding quite successfully. By augmenting them with `sovara`, you can supercharge your agent development while making sure you adhere to state-of-the-art coding practices for enterprise-grade agents.

### Why use these integrations?

- **Keep context clean**: Agent runs produce verbose logs that quickly pollute a coding agent's context window. With `so-cli`, it queries only the specific nodes it needs.
- **Structured access**: Your agent gets structured JSON data (inputs, outputs, graph topology) rather than parsing raw logs.
- **Edit and rerun**: Your agent can programmatically edit an LLM's input or output and trigger a rerun to test hypotheses.

<h3><img src="docs/media/codex.png" alt="Codex" height="24" align="absmiddle">&nbsp;&nbsp;Codex</h3>

Install globally:

```bash
so-cli install-skill --target codex
```

This copies the shared Sovara skill to `$HOME/.agents/skills/sovara/`, so you can use it from any repository. The installer only copies skill files and does not modify Codex settings.

To install it for a specific project instead:

```bash
so-cli install-skill --target codex --level project
```

That copies the skill to `.agents/skills/sovara/` under the selected project. Codex also scans `.agents/skills` from your current working directory up to the repository root, so project-level skills can be scoped to a repo or subdirectory.

Use Sovara in Codex by asking for `$sovara` explicitly, or let Codex invoke it automatically when the task matches the skill description.

Example prompts:

```text
$sovara inspect the latest run and find the first failing node
$sovara compare these two runs and explain why the outputs diverged
$sovara propose a prior based on the failure pattern in this run
```

Codex detects skill changes automatically. If an update does not appear, restart Codex.

<h3><img src="docs/media/cc.png" alt="Claude Code" height="24" align="absmiddle">&nbsp;&nbsp;Claude Code</h3>

Install globally:

```bash
so-cli install-skill --target claude
```

This copies the shared Sovara skill to `~/.claude/skills/sovara/`, so it is available across all your projects. The installer only copies skill files and does not modify Claude settings.

To install it for one project instead:

```bash
so-cli install-skill --target claude --level project
```

That copies the skill to `.claude/skills/sovara/` under the selected project. Re-open Claude Code after installation if the skill does not appear immediately.

Use Sovara in Claude Code by letting Claude invoke the skill automatically when relevant, or select it directly from the skill menu if needed.

If you want both integrations installed globally in one step, run:

```bash
so-cli install-skill
```

## Documentation

For complete documentation, installation guides, and tutorials, visit our **[Documentation Site](https://docs.sovara-labs.com/)**.

## Building from source and developing

See the [Installation Guide](https://docs.sovara-labs.com/getting-started/installation/) for development setup and the [Developer Guide](https://docs.sovara-labs.com/developer-guide/architecture/) for architecture details. More details can also be found in the READMEs of the corresponding dirs in `src/`.

## Community

- [Join our Discord](https://discord.gg/fjsNSa6TAh)
- [GitHub Issues](https://github.com/SovaraLabs/sovara/issues)
- We're just getting started on this tool and are eager to hear your feedback and resolve issues you ran into! We hope you enjoy it as much as we do.
