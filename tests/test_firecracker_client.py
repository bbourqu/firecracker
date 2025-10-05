import json
import requests

from firecracker_client import put_json


class DummyResp:
    def __init__(self, status_code=204):
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"status {self.status_code}")


def test_put_json_success(monkeypatch):
    def fake_put(url, headers=None, data=None, timeout=None):
        return DummyResp(204)

    monkeypatch.setattr(requests, 'put', fake_put)

    assert put_json('/tmp/socket', '/boot-source', {"a": 1}) is True


def test_put_json_failure(monkeypatch):
    def fake_put(url, headers=None, data=None, timeout=None):
        return DummyResp(500)

    monkeypatch.setattr(requests, 'put', fake_put)

    try:
        put_json('/tmp/socket', '/boot-source', {"a": 1})
        assert False, "should raise"
    except Exception:
        pass
