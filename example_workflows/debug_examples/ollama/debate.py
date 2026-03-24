"""
Ollama Debate Example

This example demonstrates using Ollama's OpenAI-compatible API.

Installation:
    # macOS
    brew install ollama

    # Linux
    curl -fsSL https://ollama.com/install.sh | sh

    # Windows: Download from https://ollama.com/download

Usage:
    # Start the Ollama server
    ollama serve

    # Pull a small model (in another terminal)
    ollama pull llama3.2:1b

    # Run this example
    so-record ./example_workflows/debug_examples/ollama_debate.py
"""

from openai import OpenAI


def main():
    model = "llama3.2:1b"
    # Connect to Ollama using OpenAI-compatible API
    client = OpenAI(
        base_url="http://localhost:11434/v1",
        api_key="ollama",  # Required by client but not used by Ollama
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
