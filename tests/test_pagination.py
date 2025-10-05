import mcp_server
from types import SimpleNamespace


def test_get_vms_pagination(monkeypatch):
    # create 25 dummy VMs
    dummy_vms = {f'vm{i}': SimpleNamespace(vm_id=f'vm{i}') for i in range(25)}
    def get_status(v):
        return {'vm_id': v.vm_id, 'state': 'pending'}
    dummy_mgr = SimpleNamespace(active_vms=dummy_vms, get_vm_status=get_status)
    monkeypatch.setattr(mcp_server, 'vm_mgr', dummy_mgr)

    # page 0, size 10 -> items 0..9
    res = mcp_server.get_vms_handler(page=0, page_size=10)
    assert res['page'] == 0
    assert res['page_size'] == 10
    assert res['total'] == 25
    assert len(res['items']) == 10

    # last page (page 2), size 10 -> items 20..24 (5 items)
    res2 = mcp_server.get_vms_handler(page=2, page_size=10)
    assert res2['page'] == 2
    assert len(res2['items']) == 5
