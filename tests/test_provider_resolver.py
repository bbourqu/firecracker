import os
from types import SimpleNamespace

from utils.provider_resolver import resolve_provider_url, ensure_providers


def test_default_resolution():
    url = resolve_provider_url('ollama', None)
    assert 'localhost' in url


def test_config_resolution():
    cfg = SimpleNamespace(providers=SimpleNamespace(ollama=SimpleNamespace(url='http://cfg-ollama')))
    url = resolve_provider_url('ollama', cfg)
    assert url == 'http://cfg-ollama'


def test_env_override(monkeypatch):
    monkeypatch.setenv('OLLAMA_URL', 'http://env-ollama')
    url = resolve_provider_url('ollama', None)
    assert url == 'http://env-ollama'

def test_ensure_providers_raises():
    try:
        ensure_providers(None, ['nonexistent'])
        assert False
    except ValueError:
        assert True
