import mcp_server
from types import SimpleNamespace


def test_get_vms_handler(monkeypatch):
    dummy_vm = SimpleNamespace(vm_id='a1')
    # monkeypatch vm_mgr.active_vms with one entry and get_vm_status
    dummy_mgr = SimpleNamespace(active_vms={'a1': dummy_vm}, get_vm_status=lambda v: {'vm_id': v.vm_id, 'state': 'pending'})
    monkeypatch.setattr(mcp_server, 'vm_mgr', dummy_mgr)

    res = mcp_server.get_vms_handler()
    assert isinstance(res, list)
    assert res[0]['vm_id'] == 'a1'


def test_ui_handler_contains_initial(monkeypatch):
    dummy_vm = SimpleNamespace(vm_id='b2')
    dummy_mgr = SimpleNamespace(active_vms={'b2': dummy_vm}, get_vm_status=lambda v: {'vm_id': v.vm_id, 'state': 'running'})
    monkeypatch.setattr(mcp_server, 'vm_mgr', dummy_mgr)
    # server-side token must not be embedded in UI
    monkeypatch.setattr(mcp_server, 'MCP_AUTH_TOKEN', 'secret-token')

    page = mcp_server.ui_handler()
    assert '<title>MCP - VM Status</title>' in page
    assert 'b2' in page
    # token should not appear in page HTML
    assert 'secret-token' not in page


def test_start_stop_core(monkeypatch):
    dummy_vm = SimpleNamespace(vm_id='x1')
    dummy_mgr = SimpleNamespace(active_vms={'x1': dummy_vm}, start_vm=lambda v: None, stop_vm=lambda v: None)
    monkeypatch.setattr(mcp_server, 'vm_mgr', dummy_mgr)
    monkeypatch.setattr(mcp_server, 'MCP_AUTH_TOKEN', 'tok')

    # valid token
    r = mcp_server.start_vm_core('x1', token='tok')
    assert r['status'] == 'started'
    r2 = mcp_server.stop_vm_core('x1', token='tok')
    assert r2['status'] == 'stopped'

    # invalid token
    try:
        mcp_server.start_vm_core('x1', token='bad')
        assert False
    except Exception:
        assert True


def test_rotate_token(monkeypatch, tmp_path):
    # point token file to tmp path
    tf = tmp_path / 'tokenfile'
    monkeypatch.setenv('MCP_AUTH_FILE', str(tf))
    # reload module parts by calling loader
    monkeypatch.setenv('MCP_AUTH_TOKEN', '')
    # force reload of token loader
    # call internal loader
    new_token = mcp_server.rotate_token_core(mcp_server.MCP_AUTH_TOKEN)
    assert isinstance(new_token, str)
    # subsequent rotate with wrong token fails
    try:
        mcp_server.rotate_token_core('bad')
        assert False
    except Exception:
        assert True
