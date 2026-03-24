import concurrent.futures
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


def eval_sample(prompt):
    # Simple python function that runs one sample.
    response = client.responses.create(model=model, input=prompt, temperature=0)

    response = response.output_text
    verify = f"Someone was asked to answer the question: {prompt}. The answer was: {response}. Is this correct?"

    response2 = client.responses.create(model=model, input=verify, temperature=0)

    return response2.output_text


def run_single_threaded_eval(prompt):
    """Run a single evaluation in its own context (threaded)"""
    country = prompt.split(" ")[-1][:-1]
    with sovara_launch(run_name=country):
        return eval_sample(prompt)


def threaded_parallel_example():
    """Run multiple evaluations in parallel threads"""
    print("\n5. Threaded parallel runs with ThreadPoolExecutor:")

    # Run all evaluations in parallel threads
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
        futures = [executor.submit(run_single_threaded_eval, prompt) for prompt in prompts]
        results = [f.result() for f in futures]


threaded_parallel_example()
