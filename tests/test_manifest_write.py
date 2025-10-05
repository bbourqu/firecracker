import json
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


def test_create_vm_writes_manifest(tmp_path, monkeypatch):
    cfg = DummyConfig()
    Path(cfg.paths.shared).mkdir(parents=True, exist_ok=True)
    Path(cfg.paths.results).mkdir(parents=True, exist_ok=True)

    manager = VMManager(cfg)

    # monkeypatch create_shared_disk to avoid system calls
    monkeypatch.setattr(manager, 'create_shared_disk', lambda vm_id, task_data=None: Path(f"/tmp/shared-{vm_id}.ext4"))

    vm = manager.create_vm("mtest1", task_data={"task_id": "t1", "prompt": "p", "provider": "ollama"})

    manifest_path = Path(cfg.paths.results) / vm.vm_id / "manifest.json"
    assert manifest_path.exists()
    data = json.loads(manifest_path.read_text())
    assert data["vm_id"] == "mtest1"
    assert data["state"] == "pending"
