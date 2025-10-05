import requests
from provider_client import post_with_retries


class DummyResp:
    def __init__(self, status_code=200, data=None):
        self.status_code = status_code
        self._data = data or {"ok": True}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError("err")

    def json(self):
        return self._data


def test_post_with_retries_success(monkeypatch):
    def fake_post(url, json=None, timeout=None):
        return DummyResp(200, {"res": 1})

    monkeypatch.setattr(requests, 'post', fake_post)
    res = post_with_retries('http://example', {"a": 1})
    assert res == {"res": 1}


def test_post_with_retries_retry(monkeypatch):
    calls = {'n': 0}

    def fake_post(url, json=None, timeout=None):
        calls['n'] += 1
        if calls['n'] < 2:
            return DummyResp(500)
        return DummyResp(200, {"ok": 2})

    monkeypatch.setattr(requests, 'post', fake_post)
    res = post_with_retries('http://example', {"a": 1}, retries=3, backoff=0)
    assert res == {"ok": 2}
