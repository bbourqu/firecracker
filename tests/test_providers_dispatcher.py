import os
from types import SimpleNamespace

import providers


def test_call_provider_ollama(monkeypatch):
    called = {}

    class Dummy:
        @staticmethod
        def generate(host, model, prompt, timeout=30):
            called['args'] = (host, model, prompt)
            return {'text': 'ok'}

    import providers.ollama as ollama

    monkeypatch.setattr(ollama, 'generate', Dummy.generate)
    # call using explicit url (host without scheme)
    res = providers.call_provider('ollama', 'localhost:11434', 'test-model', 'hello')
    assert res == {'text': 'ok'}
