"""Quick test to check if Serper API key works."""

import os
import json
import requests

SERPER_API_KEY = os.environ.get("SERPER_API_KEY", "")

if not SERPER_API_KEY:
    print("SERPER_API_KEY is not set in environment")
    exit(1)

print(f"Using key: {SERPER_API_KEY[:8]}...")

resp = requests.post(
    "https://google.serper.dev/search",
    headers={"X-API-KEY": SERPER_API_KEY, "Content-Type": "application/json"},
    json={"q": "1816 Divina AG Switzerland", "gl": "ch", "num": 3},
    timeout=10,
)

print(f"Status: {resp.status_code}")
print(json.dumps(resp.json(), indent=2)[:1000])
