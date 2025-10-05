import json
from pathlib import Path

from vm_manager import VMManager


class DummyProc:
    def __init__(self, pid=111):
        self.pid = pid
    def poll(self):
        return None


class DummyConfig:
    class paths:
        shared = "/tmp/firecracker-shared"
        results = "/tmp/firecracker-results"
        ubuntu_images = Path("/tmp")

    class vm:
        memory_mb = 1024
        vcpus = 1
        shutdown_timeout = 1
        def get(key, default=None):
            return False


def test_start_vm_updates_manifest(monkeypatch, tmp_path):
    cfg = DummyConfig()
    Path(cfg.paths.shared).mkdir(parents=True, exist_ok=True)
    Path(cfg.paths.results).mkdir(parents=True, exist_ok=True)

    manager = VMManager(cfg)

    # Prepare VM instance
    vm = manager.create_vm("itest1", task_data={"task_id": "t1", "prompt": "p", "provider": "ollama"})

    # monkeypatch launcher.start_launcher to return dummy proc
    def fake_start_launcher(vm_id, config_path, results_root, use_jailer=False, extra_args=None):
        return DummyProc(pid=42), Path(results_root) / vm_id

    monkeypatch.setattr('launcher.start_launcher', fake_start_launcher)

    # monkeypatch put_json to be a no-op
    import firecracker_client
    monkeypatch.setattr(firecracker_client, 'put_json', lambda sock, path, payload: True)

    manager.start_vm(vm)

    manifest_path = Path(cfg.paths.results) / vm.vm_id / "manifest.json"
    data = json.loads(manifest_path.read_text())
    assert data["state"] == "running"
