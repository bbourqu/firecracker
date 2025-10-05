import requests
from providers import ollama
from providers import openai_client


class DummyResp:
    def __init__(self, status_code=200, data=None):
        self.status_code = status_code
        self._data = data or {"result": "ok"}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError("err")

    def json(self):
        return self._data


def test_ollama_generate(monkeypatch):
    def fake_post(url, json=None, timeout=None):
        return DummyResp(200, {"text": "hello"})

    monkeypatch.setattr(requests, 'post', fake_post)
    res = ollama.generate('localhost:11434', 'model', 'hi')
    assert res['text'] == 'hello'


def test_openai_complete(monkeypatch):
    def fake_post(url, json=None, headers=None, timeout=None):
        return DummyResp(200, {"choices": [{"text": "ok"}]})

    monkeypatch.setattr(requests, 'post', fake_post)
    res = openai_client.complete('key', 'gpt-3.5', 'hi')
    assert 'choices' in res
