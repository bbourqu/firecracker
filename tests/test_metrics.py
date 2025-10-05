import mcp_server


def test_metrics_endpoint_skips_if_unavailable():
    try:
        from prometheus_client import generate_latest
    except Exception:
        import pytest
        pytest.skip('prometheus_client not installed')

    if not getattr(mcp_server, 'app', None):
        import pytest
        pytest.skip('FastAPI app not available')

    from fastapi.testclient import TestClient
    client = TestClient(mcp_server.app)
    r = client.get('/metrics')
    assert r.status_code == 200
    assert 'mcp_requests_total' in r.text
