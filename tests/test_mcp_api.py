import mcp_server
from types import SimpleNamespace
from pathlib import Path
import json


def test_create_task_endpoint(monkeypatch, tmp_path):
    # monkeypatch vm_mgr to avoid heavy operations
    dummy_vm = SimpleNamespace(vm_id='t1', config={'drives': [{'path_on_host': '/tmp/rootfs'}], 'init_img': ''})
    dummy_mgr = SimpleNamespace(create_vm=lambda vm_id, task_data=None: dummy_vm, config=SimpleNamespace(paths=SimpleNamespace(results=str(tmp_path))))
    monkeypatch.setattr(mcp_server, 'vm_mgr', dummy_mgr)

    # Call handler directly
    resp = mcp_server.create_task_handler(mcp_server.MCPTaskRequest(task_id='t1', prompt='hi', provider='ollama'))
    assert resp['vm_id'] == 't1'


def test_create_task_and_start_vm(monkeypatch, tmp_path):
    # Ensure create+start path calls start_vm on vm_mgr
    dummy_vm = SimpleNamespace(vm_id='t2', config={'drives': [{'path_on_host': '/tmp/rootfs'}], 'init_img': ''})
    started = {'ok': False}

    def create_vm(vm_id, task_data=None):
        return dummy_vm

    def start_vm(vm):
        started['ok'] = True

    dummy_mgr = SimpleNamespace(create_vm=create_vm, start_vm=start_vm, config=SimpleNamespace(paths=SimpleNamespace(results=str(tmp_path))))
    monkeypatch.setattr(mcp_server, 'vm_mgr', dummy_mgr)

    resp = mcp_server.create_task_handler(mcp_server.MCPTaskRequest(task_id='t2', prompt='hi', provider='ollama', start_vm=True))
    assert resp['vm_id'] == 't2'
    assert started['ok'] is True


def test_post_results_writes_file(monkeypatch, tmp_path):
    # prepare results dir
    res_root = tmp_path
    monkeypatch.setattr(mcp_server, 'vm_mgr', SimpleNamespace(config=SimpleNamespace(paths=SimpleNamespace(results=str(res_root)))))

    payload = mcp_server.SubagentResult(vm_id='v1', task_id='t1', smoke_test_passed=True)
    resp = mcp_server.post_results_handler(payload)
    assert resp['status'] == 'ok'
    # guest-result.json should exist
    p = res_root / 'v1' / 'guest-result.json'
    assert p.exists()
    data = json.loads(p.read_text())
    assert data['task_id'] == 't1'
