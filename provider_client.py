"""Provider client with simple retry/backoff for LLM providers.

This is a light wrapper that makes HTTP POST requests with retry/backoff.
"""
import time
from typing import Any, Dict
import requests


def post_with_retries(url: str, json: Dict[str, Any], retries: int = 3, backoff: float = 0.5, timeout: int = 10):
    last_exc = None
    for attempt in range(1, retries + 1):
        try:
            resp = requests.post(url, json=json, timeout=timeout)
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            last_exc = e
            time.sleep(backoff * attempt)
    raise last_exc
