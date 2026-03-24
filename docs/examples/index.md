# Example Workflows

Sovara includes several example workflows to help you understand how to use the tool and test your setup.

!!! note "Project Root Configuration"
    For some examples, you may need to modify your project root. Run `so-config` and set it to the root of the example repo.

## Built-in Examples

### Debug Examples

Location: `example_workflows/debug_examples/`

Over 30 simple workflows for testing different LLM providers and frameworks:

| Provider/Framework | Examples |
|-------------------|----------|
| OpenAI | `openai_debate.py`, `openai_async_debate.py`, etc. |
| Anthropic | `anthropic_debate.py`, `anthropic_document_query.py`, etc. |
| Google GenAI | `genai_debate.py` |
| CrewAI | `crewai_research_writer.py`, `crewai_multi_tool.py`, etc. |
| LangChain | `langchain_debate.py`, `langchain_tools.py`, etc. |

```bash
# Run an example
so-record ./example_workflows/debug_examples/openai_debate.py
```

These examples are included directly in the repository and don't require additional setup.

### MCP Examples

Location: `example_workflows/mcp/`

Examples demonstrating MCP (Model Context Protocol) tool integration:

```bash
so-record ./example_workflows/mcp/google_search.py
```

## External Example Workflows

The following examples are maintained as separate Git submodules. They require cloning from private repositories within the agops-project organization.

### Simple Workflows

| Example | Description |
|---------|-------------|
| `ours_doc_bench` | Questions over PDFs |
| `ours_human_eval` | Evaluate model-generated code (requires data from [openai/human-eval](https://github.com/openai/human-eval)) |

### Medium Complexity

| Example | Description |
|---------|-------------|
| `chess_text2sql` | Previously SOTA on the BIRD Text2SQL benchmark. Based on [CHESS](https://github.com/ShayanTalaei/CHESS) |
| `bird` | Our agent for the BIRD Text2SQL benchmark |

### Complex Workflows

| Example | Description |
|---------|-------------|
| `miroflow_deep_research` | MiroFlow open-source deep research agent |
| `ours_swe_bench` | SWE-bench benchmark with our own agent |

## Cloning Example Submodules

To clone an example submodule:

```bash
# Navigate to the example directory
cd example_workflows/chess_text2sql/

# Follow the README instructions to clone
# (Typically requires access to the private repo)
```

Each example directory contains a `README.md` with specific setup instructions.

## Adding Your Own Examples

To add a new example workflow:

1. Create a descriptive folder name (e.g., `example_workflows/my_agent`)

2. Create a private GitHub repo in the agops-project organization

3. Push your example code to the private repo:
   ```bash
   git init
   git add .
   git commit -m "first commit"
   git branch -M main
   git remote add origin https://github.com/agops-project/my_agent.git
   git push -u origin main
   ```

4. Add a `README.md` in your example folder describing:
   - How to clone the submodule
   - Setup instructions
   - Any known issues or quirks

5. From the sovara root, add the submodule:
   ```bash
   git submodule add https://github.com/agops-project/my_agent.git example_workflows/my_agent/repo
   ```

## Running Examples

All examples follow the same pattern:

```bash
# Activate your environment
conda activate sovara

# Set project root if needed
so-config

# Run the example
so-record ./example_workflows/EXAMPLE_NAME/script.py
```

## Next Steps

- [Understand the architecture](../developer-guide/architecture.md)
- [Learn about edge detection](../developer-guide/edge-detection.md)
