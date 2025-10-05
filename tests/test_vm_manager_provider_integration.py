import json
from types import SimpleNamespace
from pathlib import Path

import vm_manager


def test_vm_manager_records_provider_response(monkeypatch, tmp_path):
    # prepare a minimal config
    from pathlib import Path as _P
    cfg = SimpleNamespace(paths=SimpleNamespace(shared=str(tmp_path / 'shared'), results=str(tmp_path / 'results'), ubuntu_images=_P(tmp_path)), vm=SimpleNamespace(memory_mb=128, vcpus=1, shutdown_timeout=5))
    # ensure directories
    Path(cfg.paths.shared).mkdir(parents=True, exist_ok=True)
    Path(cfg.paths.results).mkdir(parents=True, exist_ok=True)

    manager = vm_manager.VMManager(cfg)

    # monkeypatch provider resolver to return a dummy url
    monkeypatch.setattr('vm_manager.resolve_provider_url', lambda p, c: 'http://dummy')

    # monkeypatch providers.call_provider to return a known value
    import providers as _providers
    monkeypatch.setattr(_providers, 'call_provider', lambda provider, url, model, prompt: {'result': 'ok'})

    # Avoid heavy disk and guest artifact operations in unit test
    monkeypatch.setattr(vm_manager.VMManager, 'create_shared_disk', lambda self, vm_id, task_data=None: Path(f"/tmp/shared-{vm_id}.ext4"))
    import tools.guest_tools as _gt
    monkeypatch.setattr(_gt, 'create_guest_tar', lambda *args, **kwargs: None)
    monkeypatch.setattr(_gt, 'create_init_overlay', lambda *args, **kwargs: None)

    # create a vm with provider in task_data - shouldn't perform network calls due to monkeypatch
    td = {'task_id': 't1', 'prompt': 'hello', 'provider': 'ollama', 'model': 'm'}
    vm = manager.create_vm('v1', task_data=td)

    # assert manifest present
    mpath = Path(cfg.paths.results) / 'v1' / 'manifest.json'
    assert mpath.exists()
    m = json.loads(mpath.read_text())
    assert m['vm_id'] == 'v1'
    # provider_response should be stored on the VM instance
    assert 'v1' in manager.active_vms
    assert manager.active_vms['v1'] is not None
