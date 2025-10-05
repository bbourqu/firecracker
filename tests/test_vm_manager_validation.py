import pytest
import tempfile
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


def test_create_vm_rejects_invalid_task_data(tmp_path):
    cfg = DummyConfig()
    # ensure directories exist
    Path(cfg.paths.shared).mkdir(parents=True, exist_ok=True)
    Path(cfg.paths.results).mkdir(parents=True, exist_ok=True)

    manager = VMManager(cfg)

    with pytest.raises(Exception):
        manager.create_vm("bad1", task_data={"prompt": "No id", "provider": "ollama"})
