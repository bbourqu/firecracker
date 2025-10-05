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


def test_create_vm_calls_provider(monkeypatch):
    cfg = DummyConfig()
    Path(cfg.paths.shared).mkdir(parents=True, exist_ok=True)
    Path(cfg.paths.results).mkdir(parents=True, exist_ok=True)

    manager = VMManager(cfg)

    # monkeypatch shared disk creation to avoid system calls
    monkeypatch.setattr(manager, 'create_shared_disk', lambda vm_id, task_data=None: Path(f"/tmp/shared-{vm_id}.ext4"))

    # monkeypatch the provider dispatcher used by vm_manager
    import providers as prov_mod
    monkeypatch.setattr(prov_mod, 'call_provider', lambda provider, url, model, prompt: {"reply": "ok"})
    # ensure provider resolver returns something
    import vm_manager as vm_mod
    monkeypatch.setattr(vm_mod, 'resolve_provider_url', lambda p, c: 'http://dummy')

    task_data = {"task_id": "t1", "prompt": "Hello", "provider": "ollama"}
    vm = manager.create_vm("pv1", task_data=task_data)

    # provider response should be recorded in task_data or vm config
    assert 'provider_response' in task_data
    assert isinstance(task_data['provider_response'], dict)
