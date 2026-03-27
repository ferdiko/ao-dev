"""
Example demonstrating the inject_priors functionality.

This example shows how to inject priors from the priors server
into an LLM prompt. The priors are automatically tracked so the UI
can show which priors were applied to which runs.

Usage:
    so-record example_workflows/debug_examples/openai/inject_priors.py
"""

from openai import OpenAI
from sovara.runner.priors import inject_priors


client = OpenAI()

# Fetch and inject priors from the priors server
# Pass a path to filter priors by folder, or None for all priors
priors_context = inject_priors(path=None, method="all")

# Build the system message with injected priors
system_message = "You are a helpful assistant."
if priors_context:
    system_message += f"\n\n{priors_context}"
    print(f"Injected priors into context:\n{priors_context[:200]}...")
else:
    print("No priors found or priors server unavailable.")

messages = [
    {"role": "developer", "content": system_message},
    {"role": "user", "content": "Hello! Can you tell me something interesting?"},
]

# Make the API call with the injected priors
completion = client.chat.completions.create(model="gpt-4o-mini", messages=messages)
response = completion.choices[0].message.content

print(f"\nAssistant: {response}")
