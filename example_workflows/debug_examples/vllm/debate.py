"""
vLLM Debate Example

This example demonstrates using vLLM's OpenAI-compatible API server.

To run this example:

1. Install vLLM

    conda create -n vllm python=3.13 -y
    conda activate vllm
    git clone https://github.com/vllm-project/vllm.git
    pip install torch torchvision
    cd vllm && VLLM_TARGET_DEVICE=cpu VLLM_BUILD_WITH_CUDA=0 pip install -e .

1. Start a vLLM server:

   VLLM_USE_CUDA=0 python -m vllm.entrypoints.openai.api_server \
        --model TinyLlama/TinyLlama-1.1B-Chat-v1.0 \
        --tensor-parallel-size 1 \
        --host 0.0.0.0 \
        --port 8000 \
        --dtype float16

2. Run this script:

   so-record ./example_workflows/debug_examples/vllm_debate.py

Note: vLLM provides an OpenAI-compatible API, so we use the OpenAI client
with a custom base_url pointing to the vLLM server.
"""

from openai import OpenAI


def main():
    model = "TinyLlama/TinyLlama-1.1B-Chat-v1.0"
    # Connect to vLLM server using OpenAI-compatible API
    # The api_key is not used by vLLM but required by the OpenAI client
    client = OpenAI(
        base_url="http://localhost:8000/v1",
        api_key="not-needed",
    )

    # First LLM: Generate a yes/no question
    question_response = client.chat.completions.create(
        model=model,
        messages=[
            {
                "role": "user",
                "content": "Come up with a simple question where there is a pro and contra opinion. Only output the question and nothing else.",
            }
        ],
        max_tokens=100,
        temperature=0.7,
    )
    question = question_response.choices[0].message.content

    # Second LLM: Argue "yes"
    yes_prompt = f"Consider this question: {question}\nWrite a short paragraph on why to answer this question with 'yes'"
    yes_response = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": yes_prompt}],
        max_tokens=200,
        temperature=0.7,
    )

    # Third LLM: Argue "no"
    no_prompt = f"Consider this question: {question}\nWrite a short paragraph on why to answer this question with 'no'"
    no_response = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": no_prompt}],
        max_tokens=200,
        temperature=0.7,
    )

    # Fourth LLM: Judge who won
    yes_text = yes_response.choices[0].message.content
    no_text = no_response.choices[0].message.content
    judge_prompt = f"Consider the following two paragraphs:\n1. {yes_text}\n2. {no_text}\nWho won the argument?"
    judge_response = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": judge_prompt}],
        max_tokens=200,
        temperature=0.7,
    )

    print(f"Question: {question}")
    print(f"\nJudge's verdict: {judge_response.choices[0].message.content}")


if __name__ == "__main__":
    main()
