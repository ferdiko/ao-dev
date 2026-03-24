# Quickstart

This guide will get you up and running with Sovara in a few minutes.

## Step 1: Create an Example Project

Create a folder called `my-agent` and add a file called `openai_example.py` with the following content:

```
from openai import OpenAI

def main():
    client = OpenAI()

    response = client.responses.create(
        model="gpt-4o-mini",
        input="Output the number 42 and nothing else",
        temperature=0
    )
    number = response.output_text

    prompt_add_1 = f"Add 1 to {number} and just output the result."
    prompt_add_2 = f"Add 2 to {number} and just output the result."

    response1 = client.responses.create(model="gpt-4o-mini", input=prompt_add_1, temperature=0)
    response2 = client.responses.create(model="gpt-4o-mini", input=prompt_add_2, temperature=0)

    sum_prompt = f"Add these two numbers together and just output the result: {response1.output_text} + {response2.output_text}"
    final_sum = client.responses.create(model="gpt-4o-mini", input=sum_prompt, temperature=0)

    print(f"Final sum: {final_sum.output_text}")

if __name__ == "__main__":
    main()
```

Run the script to verify it works:

```bash
cd my-agent
python openai_example.py
```

The output should be `87` (42 + 1 = 43, 42 + 2 = 44, 43 + 44 = 87).

## Step 2: Configure Sovara

Run `so-config` and set the project root to your `my-agent` folder:

```bash
so-config
```

## Step 3: Start the Server

Start the Sovara server:

```bash
so-server start
```

## Step 4: Run with Sovara

Install the [Sovara VS Code Extension](https://marketplace.visualstudio.com/items?itemName=SovaraLabs.sovara) from the VS Code marketplace.

Open your `my-agent` folder in VS Code, then run the example with Sovara in the terminal:

```bash
so-record openai_example.py
```

The VS Code extension will display the dataflow graph showing how data flows between the LLM calls.

## Next Steps

- [Learn all CLI commands](../user-guide/cli-commands.md)
- [Explore the VS Code extension features](../user-guide/vscode-extension.md)
- [Create subruns for batch processing](../user-guide/subruns.md)
