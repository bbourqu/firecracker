"""Minimal Ollama HTTP client wrapper.
This wraps a POST to a local Ollama server with a text prompt and returns JSON.
"""
import requests
from typing import Any, Dict


def generate(host: str, model: str, prompt: str, timeout: int = 30) -> Dict[str, Any]:
    url = f"http://{host}/api/generate"
    payload = {"model": model, "prompt": prompt}
    resp = requests.post(url, json=payload, timeout=timeout)
    resp.raise_for_status()
    return resp.json()
