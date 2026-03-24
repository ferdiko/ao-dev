"""
TODO: The below example doesn't have any concurrency since there
aren't any awaits. We need to use and patch `openai.AsyncOpenAI`
client before.
"""

import asyncio
from openai import OpenAI  # TODO: AsyncOpenAI
from sovara.runner.context_manager import sovara_launch

client = OpenAI()
model = "gpt-3.5-turbo"

# All samples in the eval set.
prompts = [
    "What is the capital of France?",
    "What is the capital of Germany?",
    "What is the capital of Italy?",
    "What is the capital of Spain?",
    "What is the capital of Portugal?",
    "What is the capital of Greece?",
    "What is the capital of Turkey?",
]


async def async_eval_sample(prompt):
    response = client.responses.create(model=model, input=prompt, temperature=0)

    response = response.output_text
    verify = f"Someone was asked to answer the question: {prompt}. The answer was: {response}. Is this correct?"

    response2 = client.responses.create(model=model, input=verify, temperature=0)

    return response2.output_text


async def run_single_async_eval(prompt):
    """Run a single evaluation in its own context"""
    country = prompt.split(" ")[-1][:-1]
    with sovara_launch(run_name=country):
        return await async_eval_sample(prompt)


async def async_parallel_example():
    """Run multiple evaluations concurrently with asyncio"""
    # Run all evaluations concurrently
    tasks = [run_single_async_eval(prompt) for prompt in prompts]

    results = await asyncio.gather(*tasks)


asyncio.run(async_parallel_example())
