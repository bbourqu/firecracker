import os
from pathlib import Path

from vm_manager import VMManager


class DummyConfig:
    class paths:
        shared = "/tmp/firecracker-shared"
        results = "/tmp/firecracker-results"
        ubuntu_images = Path("/tmp")

    class vm:
        memory_mb = 1024
        vcpus = 1
        shutdown_timeout = 1


def test_ollama_env_override(monkeypatch):
    cfg = DummyConfig()
    manager = VMManager(cfg)

    # patch create_shared_disk to avoid system calls
    monkeypatch.setattr(manager, 'create_shared_disk', lambda vm_id, task_data=None: Path(f"/tmp/shared-{vm_id}.ext4"))

    # ensure env var is set
    monkeypatch.setenv('OLLAMA_URL', 'http://remote-ollama:11434/api/generate')

    # patch providers.call_provider to capture the URL argument
    import providers as prov_mod
    captured = {}
    def fake_call(provider, url, model, prompt):
        captured['url'] = url
        return {'ok': True}

    monkeypatch.setenv('OLLAMA_URL', 'http://remote-ollama:11434/api/generate')
    monkeypatch.setattr(prov_mod, 'call_provider', fake_call)

    task_data = {"task_id": "t1", "prompt": "Hello", "provider": "ollama"}
    manager.create_vm('env1', task_data=task_data)

    assert 'remote-ollama' in captured.get('url', '')
