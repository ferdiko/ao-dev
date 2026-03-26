# pip install anthropic e2b-code-interpreter
import base64
import anthropic
from e2b_code_interpreter import Sandbox


client = anthropic.Anthropic()

model = "claude-sonnet-4-5"

# Define the tool for Python code execution
tools = [
    {
        "name": "execute_python",
        "description": "Execute python code in a Jupyter notebook cell and return result",
        "input_schema": {
            "type": "object",
            "properties": {
                "code": {
                    "type": "string",
                    "description": "The python code to execute in a single cell",
                }
            },
            "required": ["code"],
        },
    }
]

# Load an image (you can replace this with your own image path)
# For this example, we'll create a simple image or use a placeholder
image_path = "../user_files/sample_program.jpg"

with open(image_path, "rb") as image_file:
    image_data = base64.standard_b64encode(image_file.read()).decode("utf-8")
    image_media_type = "image/jpeg"

# Create the initial message with image and text
messages = [
    {
        "role": "user",
        "content": [
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": image_media_type,
                    "data": image_data,
                },
            },
            {
                "type": "text",
                "text": "This image contains code. Create a tool call that executes this code.",
            },
        ],
    }
]

# Make the first API call with tools
response = client.messages.create(
    max_tokens=1024,
    model=model,
    tools=tools,
    messages=messages,
)

# Process the response
messages.append({"role": "assistant", "content": response.content})

tool_result = None
assert response.stop_reason == "tool_use"

content_block = response.content[0]
if content_block.type == "tool_use":
    if content_block.name == "execute_python":
        with Sandbox.create() as sandbox:
            code = content_block.input["code"]
            print(f"[user_program] Executing code:\n{code}")
            execution = sandbox.run_code(code)
            result = execution.text
            print(f"[user_program] Execution result: {result}")
        tool_result = {
            "type": "tool_result",
            "tool_use_id": content_block.id,
            "content": result,
        }

# Send tool results back to the model
messages.append(
    {
        "role": "user",
        "content": [
            tool_result,
            {"type": "text", "text": "Did the code execute correctly?"}
        ]
    }
)

# Get final response
final_response = client.messages.create(
    max_tokens=1024,
    model=model,
    tools=tools,
    messages=messages,
)

# Extract final text
for content_block in final_response.content:
    if hasattr(content_block, "text"):
        print(f"[user_program] Final answer: {content_block.text}")
