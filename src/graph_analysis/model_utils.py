"""
Downloads llamafile and Qwen2.5 GGUF weights for local LLM inference.
"""

import json
import os
import socket
import subprocess
import time
import urllib.request

from ao.common.constants import MODELS_DIR, LLAMAFILE_PORT

LLAMAFILE_URL = "https://github.com/mozilla-ai/llamafile/releases/download/0.9.3/llamafile-0.9.3"
GGUF_URL = "https://huggingface.co/Qwen/Qwen2.5-1.5B-Instruct-GGUF/resolve/main/qwen2.5-1.5b-instruct-q8_0.gguf"


def _download_file(url, filename):
    path = os.path.join(MODELS_DIR, filename)
    if os.path.exists(path):
        print(f"{filename} already downloaded.")
        return path
    print(f"Downloading {filename}...")
    urllib.request.urlretrieve(url, path)
    if filename.endswith((".exe",)):
        os.chmod(path, 0o755)
    print(f"Downloaded {filename}.")
    return path


def download_full_weights():
    # .exe is needed for Windows; macOS/Linux ignore the extension.
    llamafile_path = _download_file(LLAMAFILE_URL, "llamafile.exe")
    gguf_path = _download_file(GGUF_URL, "qwen2.5-1.5b-instruct-q8_0.gguf")
    return llamafile_path, gguf_path


def start_model_server(port=LLAMAFILE_PORT):
    """Download model files if needed, then start llamafile server as a daemon."""
    llamafile_path, gguf_path = download_full_weights()
    cmd = f"{llamafile_path} -m {gguf_path} --port {port} --host 127.0.0.1"
    subprocess.Popen(
        cmd,
        shell=True,
        # stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    # Wait for server to accept connections (model loading can take a while)
    for _ in range(60):
        try:
            socket.create_connection(("127.0.0.1", port), timeout=1).close()
            print(f"Model server ready on port {port}.")
            return
        except OSError:
            time.sleep(0.5)
    raise TimeoutError(f"Model server failed to start on port {port}")


def query_model(prompt, port=LLAMAFILE_PORT):
    """Send a prompt to the llamafile server and return the response text."""
    url = f"http://127.0.0.1:{port}/v1/chat/completions"
    payload = json.dumps(
        {
            "model": "qwen",
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0,
            "top_k": 1,
            "top_p": 1,
        }
    ).encode()
    req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req) as resp:
        data = json.loads(resp.read())
    return data["choices"][0]["message"]["content"]


if __name__ == "__main__":
    start_model_server()
    print("\n\n\nOUT:", query_model("What is 2+2?"))
