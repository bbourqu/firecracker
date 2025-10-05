"""Minimal OpenAI HTTP client wrapper.
This wrapper posts to the OpenAI completions endpoint and returns parsed JSON.
In production prefer the official openai package.
"""
import requests
from typing import Any, Dict


def complete(api_key: str, model: str, prompt: str, timeout: int = 30) -> Dict[str, Any]:
    url = "https://api.openai.com/v1/completions"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload = {"model": model, "prompt": prompt, "max_tokens": 128}
    resp = requests.post(url, json=payload, headers=headers, timeout=timeout)
    resp.raise_for_status()
    return resp.json()
