"""
Downloads llamafile and Qwen2.5 GGUF weights for local LLM inference.
"""

import json
import os
import signal
import socket
import subprocess
import time
import urllib.request

from ao.common.constants import MODELS_DIR, LLAMAFILE_PORT, LLM_TIMEOUT, LLAMAFILE_URL, GGUF_URL
from ao.server.handlers.handler_utils import logger


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


def _download_full_weights():
    # .exe is needed for Windows; macOS/Linux ignore the extension.
    llamafile_path = _download_file(LLAMAFILE_URL, "llamafile.exe")
    gguf_path = _download_file(GGUF_URL, "qwen2.5-1.5b-instruct-q8_0.gguf")
    return llamafile_path, gguf_path


def start_model_server():
    """Download model files if needed, then start llamafile server as a daemon. No-op if already running."""
    try:
        socket.create_connection(("127.0.0.1", LLAMAFILE_PORT), timeout=1).close()
        print(f"Model server already running on port {LLAMAFILE_PORT}.")
        return
    except OSError:
        pass

    llamafile_path, gguf_path = _download_full_weights()
    cmd = f"{llamafile_path} --server --nobrowser -m {gguf_path} --port {LLAMAFILE_PORT} --host 127.0.0.1"
    logger.info(f"[model_server] Starting llamafile: {cmd}")
    stderr_log = os.path.join(MODELS_DIR, "llamafile_stderr.log")
    stderr_file = open(stderr_log, "w")
    proc = subprocess.Popen(
        cmd,
        shell=True,
        stdout=subprocess.DEVNULL,
        stderr=stderr_file,
        start_new_session=True,
    )
    # Wait for server to accept connections (model loading can take a while)
    for i in range(60):
        # Check if process died early
        ret = proc.poll()
        if ret is not None:
            stderr_file.close()
            with open(stderr_log) as f:
                stderr = f.read()
            logger.error(
                f"[model_server] Process exited with code {ret} after {i*0.5:.1f}s. stderr: {stderr}"
            )
            return
        try:
            socket.create_connection(("127.0.0.1", LLAMAFILE_PORT), timeout=1).close()
            logger.info(
                f"[model_server] Ready on port {LLAMAFILE_PORT} after {i*0.5:.1f}s (pid={proc.pid})"
            )
            return
        except OSError:
            time.sleep(0.5)
    logger.error(f"[model_server] Failed to start within 30s on port {LLAMAFILE_PORT}")


def stop_model_server():
    """Stop the llamafile server if it's running. No-op if not running."""
    try:
        result = subprocess.run(
            ["lsof", "-ti", f":{LLAMAFILE_PORT}"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode != 0 or not result.stdout.strip():
            print(f"No model server running on port {LLAMAFILE_PORT}.")
            return
        for pid_str in result.stdout.strip().split("\n"):
            os.kill(int(pid_str), signal.SIGTERM)
        print(f"Model server on port {LLAMAFILE_PORT} stopped.")
    except Exception as e:
        print(f"Failed to stop model server: {e}")


def query_model(prompt):
    """Send a prompt to the llamafile server. Returns response text or None on any error."""
    try:
        url = f"http://127.0.0.1:{LLAMAFILE_PORT}/v1/chat/completions"
        payload = json.dumps(
            {
                "model": "qwen",
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0,
                "top_k": 1,
                "top_p": 1,
            }
        ).encode()
        req = urllib.request.Request(
            url, data=payload, headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req, timeout=LLM_TIMEOUT) as resp:
            data = json.loads(resp.read())
        return data["choices"][0]["message"]["content"]
    except Exception as e:
        logger.error(f"[query_model] Error calling llamafile: {e}")
        return None


def get_node_label(prompt):
    """Generate a descriptive label for a graph node using the local LLM. Returns label string or None."""
    return query_model(prompt)
