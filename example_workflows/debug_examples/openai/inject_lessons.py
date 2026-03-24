"""
Example demonstrating the inject_lesson functionality.

This example shows how to inject lessons from the ao-playbook server
into an LLM prompt. The lessons are automatically tracked so the UI
can show which lessons were applied to which runs.

Usage:
    so-record example_workflows/debug_examples/openai/inject_lessons.py
"""

from openai import OpenAI
from sovara.runner.lessons import inject_lesson


client = OpenAI()

# Fetch and inject lessons from the playbook server
# Pass a path to filter lessons by folder, or None for all lessons
lessons_context = inject_lesson(path=None)

# Build the system message with injected lessons
system_message = "You are a helpful assistant."
if lessons_context:
    system_message += f"\n\n{lessons_context}"
    print(f"Injected lessons into context:\n{lessons_context[:200]}...")
else:
    print("No lessons found or playbook server unavailable.")

messages = [
    {"role": "developer", "content": system_message},
    {"role": "user", "content": "Hello! Can you tell me something interesting?"},
]

# Make the API call with the injected lessons
completion = client.chat.completions.create(model="gpt-4o-mini", messages=messages)
response = completion.choices[0].message.content

print(f"\nAssistant: {response}")
