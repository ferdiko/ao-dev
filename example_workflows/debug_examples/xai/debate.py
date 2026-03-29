import os

from openai import OpenAI


def _chat(client: OpenAI, model: str, prompt: str) -> str:
    response = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        temperature=0,
    )
    return response.choices[0].message.content or ""


def main():
    client = OpenAI(
        api_key=os.environ["XAI_API_KEY"],
        base_url="https://api.x.ai/v1",
    )
    model = "grok-4-fast-non-reasoning"

    question = _chat(
        client,
        model,
        "Come up with a simple question where there is a pro and contra opinion. "
        "Only output the question and nothing else.",
    )

    yes_text = _chat(
        client,
        model,
        f"Consider this question: {question}\nWrite a short paragraph on why to answer this question with 'yes'",
    )
    no_text = _chat(
        client,
        model,
        f"Consider this question: {question}\nWrite a short paragraph on why to answer this question with 'no'",
    )
    verdict = _chat(
        client,
        model,
        f"Consider the following two paragraphs:\n1. {yes_text}\n2. {no_text}\nWho won the argument?",
    )

    print(f"Question: {question}")
    print(f"\nJudge's verdict: {verdict}")


if __name__ == "__main__":
    main()
