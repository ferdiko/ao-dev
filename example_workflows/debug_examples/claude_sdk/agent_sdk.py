"""
Claude Agent SDK Example

This uses the official Claude Agent SDK to create an agent that can
make multiple API calls, similar to how Claude Code works.
"""

import asyncio
import os
from claude_agent_sdk import query, ClaudeAgentOptions


async def main():
    """Run an agent that solves a research question using Claude Code's tools."""

    options = ClaudeAgentOptions(
        system_prompt="""You are a thorough research agent. When given a question,
        use available tools to gather information, read files, search the codebase,
        and perform calculations as needed. Think step by step.""",
        permission_mode="acceptEdits",  # Auto-accept file edits
        allowed_tools=["Bash", "Glob", "Grep", "Read", "Write", "WebSearch"],
        cwd=os.getcwd(),
    )

    prompt = """
    Analyze the structure of this project and tell me:
    1. What Python files exist in the erp_demo directory?
    2. What are the main classes/functions in each file?
    3. Give a brief summary of what this codebase does.
    """

    print("=" * 70)
    print("CLAUDE AGENT SDK - Running Agent")
    print("=" * 70)
    print(f"\nPrompt: {prompt.strip()}")
    print("-" * 70)

    async for message in query(prompt=prompt, options=options):
        # Each message is a response from the agent
        print(message)


if __name__ == "__main__":
    asyncio.run(main())
