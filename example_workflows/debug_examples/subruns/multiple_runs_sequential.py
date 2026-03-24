"""
This script is to debug the `with` context manager which allows
the user to create different runs from the same script run (e.g.,
needed for running evals).
"""

from openai import OpenAI
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


# Simple python function that runs one sample.
def eval_sample(prompt):
    response = client.responses.create(model=model, input=prompt, temperature=0)

    response = response.output_text
    verify = f"Someone was asked to answer the question: {prompt}. The answer was: {response}. Is this correct?"

    response2 = client.responses.create(model=model, input=verify, temperature=0)

    return response2.output_text


# Run all samples sequentially.
for prompt in prompts:
    country = prompt.split(" ")[-1][:-1]
    with sovara_launch(run_name=country):
        eval_sample(prompt)
