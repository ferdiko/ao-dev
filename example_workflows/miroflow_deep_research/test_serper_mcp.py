"""Test Serper google_search via MCP subprocess — replicates MiroFlow's exact setup."""

import os
import json
import asyncio
from mcp.client.stdio import stdio_client
from mcp import ClientSession, StdioServerParameters

SERPER_API_KEY = os.environ.get("SERPER_API_KEY", "")


async def test_google_search():
    if not SERPER_API_KEY:
        print("SERPER_API_KEY is not set")
        return

    print(f"Using key: {SERPER_API_KEY[:8]}...")

    arguments = {
        "q": "1816 Divina AG Switzerland",
        "gl": "ch",
        "hl": "en",
        "num": 3,
        "page": 1,
        "autocorrect": False,
    }

    # ── Test 1: MiroFlow's exact env (broken — only SERPER_API_KEY) ──
    print("\n=== Test 1: MiroFlow's env (SERPER_API_KEY only) ===")
    server_params_broken = StdioServerParameters(
        command="npx",
        args=["-y", "serper-search-scrape-mcp-server"],
        env={"SERPER_API_KEY": SERPER_API_KEY},
    )
    await _run_search(server_params_broken, arguments)

    # ── Test 2: Full env (inherited + SERPER_API_KEY) ──
    print("\n=== Test 2: Full env (os.environ + SERPER_API_KEY) ===")
    server_params_fixed = StdioServerParameters(
        command="npx",
        args=["-y", "serper-search-scrape-mcp-server"],
        env={**os.environ, "SERPER_API_KEY": SERPER_API_KEY},
    )
    await _run_search(server_params_fixed, arguments)


async def _run_search(server_params, arguments):
    try:
        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write, sampling_callback=None) as session:
                await session.initialize()
                print("  MCP session initialized OK")
                tool_result = await session.call_tool("google_search", arguments=arguments)
                text = tool_result.content[-1].text if tool_result.content else ""
                if not text.strip():
                    print("  ERROR: empty result")
                else:
                    print(f"  SUCCESS: got {len(text)} chars")
                    print(f"  Preview: {text[:300]}")
    except Exception as e:
        print(f"  FAILED: {e}")


if __name__ == "__main__":
    asyncio.run(test_google_search())
