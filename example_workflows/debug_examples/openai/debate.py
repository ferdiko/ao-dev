import time
start = time.time()
from openai import OpenAI
from sovara.runner.context_manager import log

def main():
    client = OpenAI()

    # First LLM: Generate a yes/no question
    question_response = client.responses.create(
        model="gpt-4o-mini",
        input="Come up with a simple question where there is a pro and contra opinion. Only output the question and nothing else.",
        temperature=0,
    )
    question = question_response.output_text

    # Second LLM: Argue "yes"
    yes_prompt = f"Consider this question: {question}\nWrite a short paragraph on why to answer this question with 'yes'"
    yes_response = client.responses.create(
        model="gpt-4o-mini", input=yes_prompt, temperature=0
    )

    # Third LLM: Argue "no"
    no_prompt = f"Consider this question: {question}\nWrite a short paragraph on why to answer this question with 'no'"
    no_response = client.responses.create(
        model="gpt-4o-mini", input=no_prompt, temperature=0
    )

    # Fourth LLM: Judge who won
    judge_prompt = f"Consider the following two paragraphs:\n1. {yes_response.output_text}\n2. {no_response.output_text}\nWho won the argument?"
    judge_response = client.responses.create(
        model="gpt-4o-mini", input=judge_prompt, temperature=0
    )

    print(f"Question: {question}")
    print(f"\nJudge's verdict: {judge_response.output_text}")
    print(time.time() - start)

    from random import random
    log(runtime=time.time() - start, success=random() > 0.5)

if __name__ == "__main__":
    main()

