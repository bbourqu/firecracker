import json
from types import SimpleNamespace
import mcp_server


def test_mcp_end_to_end(monkeypatch, tmp_path):
    try:
        from fastapi.testclient import TestClient
    except Exception:
        import pytest
        pytest.skip('fastapi not installed; skipping integration test')

    if not getattr(mcp_server, 'app', None):
        import pytest
        pytest.skip('FastAPI app not available; skipping')

    # Setup dummy VM and manager
    class DummyVM:
        def __init__(self, vm_id):
            self.vm_id = vm_id
            self.config = {'drives': [{'path_on_host': '/fake.img'}]}

    class DummyMgr:
        def __init__(self):
            self.active_vms = {'vm1': DummyVM('vm1')}
            self.config = SimpleNamespace(paths=SimpleNamespace(results=str(tmp_path)))

        def get_vm_status(self, vm):
            return {'vm_id': vm.vm_id, 'state': getattr(vm, 'state', 'pending'), 'memory_mb': 512, 'vcpus': 1}

        def start_vm(self, vm):
            vm.state = 'running'

        def stop_vm(self, vm):
            vm.state = 'stopped'

        def create_vm(self, task_id, task_data=None):
            return DummyVM(task_id)

    dummy = DummyMgr()
    monkeypatch.setattr(mcp_server, 'vm_mgr', dummy)
    # use a known token
    monkeypatch.setattr(mcp_server, 'MCP_AUTH_TOKEN', 'itoken')

    client = TestClient(mcp_server.app)

    # list vms
    r = client.get('/v1/vms')
    assert r.status_code == 200
    j = r.json()
    assert isinstance(j, list)
    assert any(v.get('vm_id') == 'vm1' for v in j)

    # start vm (auth header)
    r = client.post('/v1/vms/vm1/start', headers={'Authorization': 'Bearer itoken'})
    assert r.status_code == 200
    assert r.json().get('status') == 'started'

    # stop vm
    r = client.post('/v1/vms/vm1/stop', headers={'Authorization': 'Bearer itoken'})
    assert r.status_code == 200
    assert r.json().get('status') == 'stopped'

    # rotate token
    r = client.post('/v1/token/rotate', headers={'Authorization': 'Bearer itoken'})
    assert r.status_code == 200
    new = r.json().get('token')
    assert isinstance(new, str) and new
    assert mcp_server.MCP_AUTH_TOKEN == new

    # create task
    payload = {'task_id': 't42', 'prompt': 'hello', 'provider': 'p1'}
    r = client.post('/v1/tasks', json=payload)
    assert r.status_code in (200, 202)
    data = r.json()
    assert data.get('vm_id') == 't42'

    # post results
    res_payload = {'vm_id': 'vm1', 'task_id': 't42', 'smoke_test_passed': True}
    r = client.post('/v1/results', json=res_payload)
    assert r.status_code == 200
    assert r.json().get('status') == 'ok'

    # guest-result.json should be written
    p = tmp_path / 'vm1' / 'guest-result.json'
    assert p.exists()
    loaded = json.loads(p.read_text())
    assert loaded.get('vm_id') == 'vm1'
