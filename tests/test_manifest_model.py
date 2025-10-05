import json
from datetime import datetime, timezone
from pathlib import Path


def make_manifest(vm_id: str):
    return {
        "vm_id": vm_id,
        "image": "ubuntu-22.04.squashfs",
        "memory_mb": 1024,
        "vcpus": 1,
        "network_mode": "slirp",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "state": "pending"
    }


def test_manifest_serialization(tmp_path: Path):
    vm_id = "testvm01"
    manifest = make_manifest(vm_id)
    p = tmp_path / f"{vm_id}-manifest.json"
    p.write_text(json.dumps(manifest))

    loaded = json.loads(p.read_text())
    assert loaded["vm_id"] == vm_id
    assert "created_at" in loaded
    assert loaded["state"] == "pending"


def test_manifest_missing_optional_defaults():
    # If optional fields omitted, our model consumer should still work
    minimal = {"vm_id": "m1", "state": "pending", "created_at": datetime.now(timezone.utc).isoformat()}
    # serialization round-trip
    s = json.dumps(minimal)
    loaded = json.loads(s)
    assert loaded["vm_id"] == "m1"
