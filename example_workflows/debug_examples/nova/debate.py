import boto3


def _chat(client, model: str, prompt: str) -> str:
    response = client.converse(
        modelId=model,
        messages=[
            {
                "role": "user",
                "content": [{"text": prompt}],
            }
        ],
        inferenceConfig={
            "temperature": 0,
            "maxTokens": 256,
        },
    )
    return response["output"]["message"]["content"][0]["text"]


def main():
    client = boto3.client("bedrock-runtime")
    model = "amazon.nova-lite-v1:0"

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
