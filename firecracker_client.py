"""Simple Firecracker control plane HTTP client for Unix socket-based API.

Provides a helper to PUT JSON payloads to the Firecracker API socket and
interpret 204 responses as success.
"""
import json
from typing import Any
from pathlib import Path

import requests


def _unix_socket_url(socket_path: str, path: str) -> str:
    # requests doesn't support unix sockets natively without adapters; many
    # environments have requests-unixsocket installed. For tests we assume the
    # caller will mock requests.put, so keep a consistent URL form.
    sock = Path(socket_path)
    return f"http+unix://{sock.as_posix()}:{path}"


def put_json(socket_path: str, path: str, payload: Any, timeout: int = 5) -> bool:
    """PUT JSON payload to the Firecracker API socket path.

    Returns True on HTTP 204 response. Raises requests.RequestException on error.
    """
    url = _unix_socket_url(socket_path, path)
    headers = {"Content-Type": "application/json"}
    data = json.dumps(payload)

    # In real usage, the adapter from requests-unixsocket is recommended. For
    # unit tests we typically patch requests.put, so this function is easy to
    # mock.
    resp = requests.put(url, headers=headers, data=data, timeout=timeout)
    if resp.status_code == 204:
        return True
    resp.raise_for_status()
    return False
