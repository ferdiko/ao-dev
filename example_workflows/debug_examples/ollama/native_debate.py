"""
Ollama Native Client Debate Example

This example demonstrates using Ollama's native Python client.

Installation:
    # Install Ollama
    # macOS: brew install ollama
    # Linux: curl -fsSL https://ollama.com/install.sh | sh
    # Windows: Download from https://ollama.com/download

    # Install the Python client
    pip install ollama

Usage:
    # Start the Ollama server
    ollama serve

    # Pull a model (in another terminal)
    ollama pull llama3.2:1b

    # Run this example
    so-record ./example_workflows/debug_examples/ollama_native_debate.py
"""

import ollama


def main():
    model = "llama3.2:1b"

    # First LLM: Generate a yes/no question
    print("Step 1: Generating a debate question...")
    question_response = ollama.chat(
        model=model,
        messages=[
            {
                "role": "user",
                "content": "Come up with a simple question where there is a pro and contra opinion. Only output the question and nothing else.",
            }
        ],
    )
    question = question_response.message.content.strip()
    print(f"Question: {question}")

    # Second LLM: Argue "yes"
    print("\nStep 2: Arguing 'yes'...")
    yes_prompt = f"Consider this question: {question}\nWrite a short paragraph on why to answer this question with 'yes'"
    yes_response = ollama.chat(
        model=model,
        messages=[{"role": "user", "content": yes_prompt}],
    )
    yes_text = yes_response.message.content.strip()

    # Third LLM: Argue "no"
    print("Step 3: Arguing 'no'...")
    no_prompt = f"Consider this question: {question}\nWrite a short paragraph on why to answer this question with 'no'"
    no_response = ollama.chat(
        model=model,
        messages=[{"role": "user", "content": no_prompt}],
    )
    no_text = no_response.message.content.strip()

    # Fourth LLM: Judge who won
    print("\nStep 4: Judging the argument...")
    judge_prompt = f"Consider the following two paragraphs:\n1. {yes_text}\n2. {no_text}\nWho won the argument?"
    judge_response = ollama.chat(
        model=model,
        messages=[{"role": "user", "content": judge_prompt}],
    )

    print(f"\nJudge's verdict: {judge_response.message.content.strip()}")


if __name__ == "__main__":
    main()
