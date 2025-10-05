try:
    from fastapi import FastAPI, HTTPException, Header
    from pydantic import BaseModel
except Exception:
    # Provide minimal stubs for test-time import when FastAPI/pydantic not installed
    FastAPI = lambda *args, **kwargs: None  # type: ignore
    class HTTPException(Exception):
        def __init__(self, status_code=500, detail=None):
            super().__init__(detail)
    # Provide a minimal BaseModel replacement
    class BaseModel(dict):
        def __init__(self, **data):
            dict.__init__(self, data)
            for k, v in data.items():
                setattr(self, k, v)
        def dict(self):
            return dict(self)

from typing import Optional
from vm_manager import VMManager
from omegaconf import OmegaConf
from pathlib import Path
import os
import time
import json
import html
import secrets
import tempfile
import stat
import asyncio

try:
    app = FastAPI(title="MCP Control Plane")
    HAS_FASTAPI = True
except Exception:
    app = None
    HAS_FASTAPI = False


class MCPTaskRequest(BaseModel):
    task_id: str
    prompt: str
    provider: str
    start_vm: Optional[bool] = False
    model: Optional[str] = None
    timeout_seconds: Optional[int] = None


class SubagentResult(BaseModel):
    vm_id: str
    task_id: str
    smoke_test_passed: bool
    generated_artifact_refs: Optional[list] = None
    logs_ref: Optional[str] = None


# Create a simple VMManager with default config
conf = OmegaConf.create({
    "paths": {"shared": "./results/shared", "results": "./results", "ubuntu_images": "."},
    "vm": {"memory_mb": 1024, "vcpus": 1, "shutdown_timeout": 5}
})
vm_mgr = VMManager(conf)

# Simple token-based auth: generated at startup and logged
MCP_AUTH_FILE = os.getenv('MCP_AUTH_FILE', '.mcp_token')


def _load_auth_token() -> str:
    # precedence: env MCP_AUTH_TOKEN > file at MCP_AUTH_FILE > generate and write
    env_token = os.getenv('MCP_AUTH_TOKEN')
    if env_token:
        return env_token
    try:
        p = Path(MCP_AUTH_FILE)
        if p.exists():
            # ensure we only read files the process can access
            try:
                return p.read_text().strip()
            except Exception:
                return ''
    except Exception:
        pass
    # generate and write
    token = secrets.token_urlsafe(24)
    try:
        # atomic write: write to temp file then replace
        p = Path(MCP_AUTH_FILE)
        td = tempfile.NamedTemporaryFile(delete=False, dir=str(p.parent) if p.parent.exists() else None)
        try:
            td.write(token.encode('utf-8'))
            td.flush(); td.close()
            os.replace(td.name, str(p))
            try:
                p.chmod(0o600)
            except Exception:
                pass
        finally:
            try:
                if os.path.exists(td.name):
                    os.remove(td.name)
            except Exception:
                pass
    except Exception:
        pass
    try:
        print(f"MCP auth token: {token}")
    except Exception:
        pass
    return token


MCP_AUTH_TOKEN = _load_auth_token()


def _check_token(token: Optional[str]) -> bool:
    if not MCP_AUTH_TOKEN:
        return True
    return bool(token) and token == MCP_AUTH_TOKEN


def start_vm_core(vm_id: str, token: Optional[str] = None):
    """Core start VM function used by route wrappers and tests.

    Raises HTTPException on auth failure.
    """
    if not _check_token(token):
        raise HTTPException(status_code=401, detail="invalid auth token")
    try:
        vm = vm_mgr.active_vms.get(vm_id)
        if not vm:
            raise HTTPException(status_code=404, detail="vm not found")
        vm_mgr.start_vm(vm)
        try:
            audit_action('start', vm_id)
        except Exception:
            pass
        return {"status": "started", "vm_id": vm_id}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


def stop_vm_core(vm_id: str, token: Optional[str] = None):
    if not _check_token(token):
        raise HTTPException(status_code=401, detail="invalid auth token")
    try:
        vm = vm_mgr.active_vms.get(vm_id)
        if not vm:
            raise HTTPException(status_code=404, detail="vm not found")
        vm_mgr.stop_vm(vm)
        try:
            audit_action('stop', vm_id)
        except Exception:
            pass
        return {"status": "stopped", "vm_id": vm_id}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


def get_logs_core(vm_id: str):
    # return guest-result.json if present, else empty string
    try:
        results_dir = Path(vm_mgr.config.paths.results) / vm_id
        p = results_dir / 'guest-result.json'
        if p.exists():
            return p.read_text()
        # try generic log file
        lf = results_dir / 'vm.log'
        if lf.exists():
            return lf.read_text()
        return ''
    except Exception:
        return ''


def rotate_token_core(current_token: Optional[str]) -> str:
    """Rotate the auth token. Requires current token to match."""
    if not _check_token(current_token):
        raise HTTPException(status_code=401, detail='invalid auth token')
    new = secrets.token_urlsafe(24)
    try:
        p = Path(MCP_AUTH_FILE)
        # atomic write
        td = tempfile.NamedTemporaryFile(delete=False, dir=str(p.parent) if p.parent.exists() else None)
        try:
            td.write(new.encode('utf-8'))
            td.flush(); td.close()
            os.replace(td.name, str(p))
            try:
                p.chmod(0o600)
            except Exception:
                pass
        finally:
            try:
                if os.path.exists(td.name):
                    os.remove(td.name)
            except Exception:
                pass
    except Exception:
        pass
    # update in-memory token
    global MCP_AUTH_TOKEN
    MCP_AUTH_TOKEN = new
    try:
        audit_action('rotate', None)
    except Exception:
        pass
    return new


def audit_action(action: str, vm_id: Optional[str] = None, actor: Optional[str] = None):
    """Append an audit entry to the audit log under results directory."""
    try:
        data = {
            'ts': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
            'action': action,
            'vm_id': vm_id,
            'actor': actor,
        }
        # choose results dir if available
        try:
            base = Path(vm_mgr.config.paths.results)
        except Exception:
            base = Path('./')
        base.mkdir(parents=True, exist_ok=True)
        p = base / 'mcp-audit.log'
        with open(p, 'a') as f:
            f.write(json.dumps(data) + '\n')
    except Exception:
        pass


def create_task_handler(req: MCPTaskRequest):
    try:
        vm = vm_mgr.create_vm(req.task_id, task_data=req.dict())
        # Optionally start the VM immediately if requested
        try:
            if getattr(req, 'start_vm', False):
                # start_vm may accept an api key in some setups; we leave it None here
                vm_mgr.start_vm(vm)
        except Exception:
            # don't fail the request if starting the VM fails; log and carry on
            pass
        # return minimal VMInstance schema
        def _get_config_attr(name, default=None):
            cfg = getattr(vm_mgr, 'config', None)
            if cfg is None:
                return default
            vm_cfg = getattr(cfg, 'vm', None)
            if vm_cfg is None and hasattr(cfg, 'get'):
                try:
                    vm_cfg = cfg.get('vm')
                except Exception:
                    vm_cfg = None
            if vm_cfg is None:
                return default
            if isinstance(vm_cfg, dict):
                return vm_cfg.get(name, default)
            return getattr(vm_cfg, name, default)

        memory_mb = _get_config_attr('memory_mb')
        vcpus = _get_config_attr('vcpus')

        return {
            "vm_id": vm.vm_id,
            "image": vm.config.get('drives', [{}])[0].get('path_on_host'),
            "memory_mb": memory_mb,
            "vcpus": vcpus,
            "state": "pending"
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


def post_results_handler(res: SubagentResult):
    # locate manifest and write guest-result.json
    results_dir = Path(vm_mgr.config.paths.results) / res.vm_id
    results_dir.mkdir(parents=True, exist_ok=True)
    with open(results_dir / "guest-result.json", 'w') as f:
        json.dump(res.dict(), f)
    # update manifest state
    try:
        # read manifest JSON
        mpath = results_dir / "manifest.json"
        if mpath.exists():
            m = json.loads(mpath.read_text())
            m['state'] = 'succeeded' if res.smoke_test_passed else 'failed'
            mpath.write_text(json.dumps(m, indent=2))
    except Exception:
        pass
    return {"status": "ok"}


def get_vms_handler(page: Optional[int] = None, page_size: Optional[int] = None):
    """Return a paginated list of VM statuses from the VM manager.

    Query params: page (0-based), page_size
    Returns: {items: [...], page, page_size, total}
    """
    try:
        all_vms = []
        for vm in vm_mgr.active_vms.values():
            try:
                status = vm_mgr.get_vm_status(vm)
            except Exception:
                status = {"vm_id": getattr(vm, 'vm_id', None)}
            all_vms.append(status)
        total = len(all_vms)
        # if pagination params not provided, return legacy list for backwards compatibility
        if page is None and page_size is None:
            return all_vms
        if page is None or page_size is None:
            return {"items": all_vms, "page": 0, "page_size": total or 0, "total": total}
        # sanitize
        try:
            p = int(page)
            ps = int(page_size)
        except Exception:
            raise HTTPException(status_code=400, detail='invalid pagination params')
        if ps <= 0:
            raise HTTPException(status_code=400, detail='page_size must be > 0')
        start = p * ps
        end = start + ps
        items = all_vms[start:end]
        return {"items": items, "page": p, "page_size": ps, "total": total}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


def ui_handler():
        """Return a simple HTML UI that shows current VM statuses and polls the JSON endpoint."""
        try:
                initial = json.dumps(get_vms_handler())
                safe = html.escape(initial)
                # Do NOT embed the server-side token in the UI HTML. Operators should paste or save the token locally.
                safe_token = ''

                html_template = """<!doctype html>
<html>
    <head>
        <meta charset="utf-8" />
        <title>MCP - VM Status</title>
        <style>
            :root{--bg:#f7f9fc;--card:#fff;--accent:#0366d6}
            body{font-family: Inter,Segoe UI,Roboto,Arial,sans-serif;background:var(--bg);color:#111;margin:0;padding:20px}
            .container{max-width:1100px;margin:0 auto}
            header{display:flex;align-items:center;justify-content:space-between;margin-bottom:16px}
            .card{background:var(--card);padding:16px;border-radius:8px;box-shadow:0 1px 3px rgba(16,24,40,0.06)}
            table{width:100%;border-collapse:collapse}
            th,td{padding:8px;border-bottom:1px solid #eee;text-align:left}
            th{font-weight:600;color:#333}
            .controls{display:flex;gap:8px;align-items:center}
            button{background:var(--accent);color:#fff;border:0;padding:8px 10px;border-radius:6px;cursor:pointer}
            button.secondary{background:#6b7280}
            .token-box{display:flex;gap:8px;align-items:center}
            pre#logview{white-space:pre-wrap;word-break:break-word;max-height:60vh;overflow:auto;background:#0b1220;color:#e6eef8;padding:12px;border-radius:6px}
            .modal{position:fixed;left:50%;top:50%;transform:translate(-50%,-50%);z-index:40;max-width:90%;width:800px}
            .hidden{display:none}
        </style>
    </head>
    <body>
        <div class="container">
            <header>
                <h1>MCP VM Status</h1>
                <div class="token-box card">
                    <div>
                        <small style="color:#666">Operator token</small>
                        <div style="display:flex;gap:8px;align-items:center">
                            <input id="tokenInput" style="font-family:monospace;padding:6px;border-radius:6px;border:1px solid #ddd" />
                            <button id="copyBtn">Copy</button>
                            <button id="loginBtn" class="secondary">Save</button>
                            <button id="logoutBtn" class="secondary">Clear</button>
                        </div>
                    </div>
                </div>
            </header>

            <div id="status" class="card"></div>

            <div id="logModal" class="modal hidden card">
                <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px">
                    <strong>VM Logs</strong>
                    <div><button id="closeLog">Close</button></div>
                </div>
                <pre id="logview">No logs</pre>
            </div>
        </div>

        <script>
            const initial = JSON.parse("__SAFE__");
            // embeddedToken intentionally empty for security
            const embeddedToken = "";
            const tokenInput = document.getElementById('tokenInput');
            const copyBtn = document.getElementById('copyBtn');
            const loginBtn = document.getElementById('loginBtn');
            const logoutBtn = document.getElementById('logoutBtn');

            function getStoredToken(){
                return localStorage.getItem('mcp_token') || '';
            }
            function setStoredToken(t){ localStorage.setItem('mcp_token', t || ''); }
            function clearStoredToken(){ localStorage.removeItem('mcp_token'); }

            // initialize token input: prefer stored (localStorage); do NOT fall back to server-embedded token
            tokenInput.value = getStoredToken() || '';

            copyBtn.addEventListener('click', async ()=>{
                try{ await navigator.clipboard.writeText(tokenInput.value || ''); copyBtn.textContent = 'Copied'; setTimeout(()=>copyBtn.textContent='Copy',1200);}catch(e){console.warn(e)}
            });
            loginBtn.addEventListener('click', ()=>{ setStoredToken(tokenInput.value||''); loginBtn.textContent='Saved'; setTimeout(()=>loginBtn.textContent='Save',1200); });
            logoutBtn.addEventListener('click', ()=>{ clearStoredToken(); tokenInput.value=''; });

            // pagination state
            let page = 0;
            const pageSize = 8;
            function render(vms){
                if(!vms || vms.length===0){ document.getElementById('status').innerHTML = '<p class="card">No VMs</p>'; return; }
                // filter by search
                const q = (document.getElementById('filter')||{value:''}).value.toLowerCase();
                const filtered = vms.filter(v => (v.vm_id||'').toLowerCase().includes(q));
                const total = filtered.length;
                const pages = Math.max(1, Math.ceil(total / pageSize));
                if(page >= pages) page = pages - 1;
                const start = page * pageSize;
                const slice = filtered.slice(start, start + pageSize);

                let html = '<div style="margin-bottom:8px;display:flex;justify-content:space-between;align-items:center"><div>Showing '+(start+1)+'-'+(start+slice.length)+' of '+total+'</div><div><button onclick="prevPage()" class="secondary">Prev</button>&nbsp;<button onclick="nextPage()" class="secondary">Next</button></div></div>';
                html += '<table><thead><tr><th>vm_id</th><th>state</th><th>memory_mb</th><th>vcpus</th><th>actions</th></tr></thead><tbody>';
                for(const v of slice){
                    const id = v.vm_id || '';
                    html += `<tr><td>${id}</td><td>${v.state||''}</td><td>${v.memory_mb||''}</td><td>${v.vcpus||''}</td><td>`+
                            `<button onclick="doAction('${id}','start')">Start</button>&nbsp;`+
                            `<button onclick="doAction('${id}','stop')">Stop</button>&nbsp;`+
                            `<button onclick="viewLogs('${id}')" class='secondary'>View logs</button>`+
                            `</td></tr>`;
                }
                html += '</tbody></table>';
                document.getElementById('status').innerHTML = html;
            }

            function nextPage(){ page++; fetchAndRender(); }
            function prevPage(){ if(page>0) { page--; fetchAndRender(); } }

            async function fetchAndRender(){
                try{
                    const qs = `?page=${page}&page_size=${pageSize}`;
                    const r = await fetch('/v1/vms' + qs);
                    if(!r.ok){
                        // fallback to unpaginated
                        const rr = await fetch('/v1/vms');
                        const j = await rr.json();
                        render(j.items || j);
                        return;
                    }
                    const j = await r.json();
                    // server returns {items, page, page_size, total}
                    if(j && j.items){
                        render(j.items);
                    } else {
                        render(j.items || j);
                    }
                }catch(e){ console.warn(e); }
            }

            // initial render: try paginated fetch
            fetchAndRender();

            async function doAction(vmId, action){
                const token = getStoredToken() || tokenInput.value || '';
                try{
                    const headers = {};
                    if(token) headers['Authorization'] = 'Bearer ' + token;
                    const resp = await fetch('/v1/vms/' + encodeURIComponent(vmId) + '/' + action, { method: 'POST', headers });
                    if(!resp.ok) console.warn('action failed', resp.status);
                }catch(e){ console.warn(e); }
            }

            async function viewLogs(vmId){
                const token = getStoredToken() || tokenInput.value || '';
                document.getElementById('logview').textContent = 'Loading...';
                document.getElementById('logModal').classList.remove('hidden');
                // Try websocket first
                try{
                    const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
                    const wsUrl = proto + '//' + location.host + '/v1/vms/' + encodeURIComponent(vmId) + '/logs/ws';
                    const ws = new WebSocket(wsUrl);
                    ws.onmessage = (ev)=>{
                        const cur = document.getElementById('logview').textContent || '';
                        document.getElementById('logview').textContent = cur + '\n' + ev.data;
                    };
                    ws.onopen = ()=>{ console.info('ws open'); };
                    ws.onclose = ()=>{ console.info('ws closed'); };
                    // close on modal close
                    document.getElementById('closeLog').onclick = ()=>{ try{ ws.close(); }catch(e){}; document.getElementById('logModal').classList.add('hidden'); };
                    return;
                }catch(e){
                    console.warn('ws failed, falling back', e);
                }

                // fallback to fetching whole log
                try{
                    const headers = {};
                    if(token) headers['Authorization'] = 'Bearer ' + token;
                    const r = await fetch('/v1/vms/' + encodeURIComponent(vmId) + '/logs', { headers });
                    const text = await r.text();
                    document.getElementById('logview').textContent = text || '(no logs)';
                }catch(e){ console.warn(e); document.getElementById('logview').textContent = '(error)'; }
            }

            document.getElementById('closeLog').addEventListener('click', ()=>{
                document.getElementById('logModal').classList.add('hidden');
            });

            setInterval(async ()=>{
                try{
                    const r = await fetch('/v1/vms');
                    const j = await r.json();
                    render(j);
                }catch(e){ console.warn(e); }
            }, 3000);
        </script>
    </body>
</html>"""

                html_page = html_template.replace('__SAFE__', safe).replace('__TOKEN__', safe_token)
                return html_page
        except Exception as e:
                raise HTTPException(status_code=500, detail=str(e))


if HAS_FASTAPI and app is not None:
    # Register metrics endpoint if prometheus_client available
    try:
        import metrics as _metrics

        @app.get('/metrics')
        def _metrics():
            data, ctype = _metrics.metrics_response()
            from fastapi.responses import Response

            return Response(content=data, media_type=ctype)
    except Exception:
        pass

    # Simple middleware to count requests
    try:
        from starlette.middleware.base import BaseHTTPMiddleware
        from metrics import REQUEST_COUNT

        @app.middleware('http')
        async def _count_requests(request, call_next):
            resp = await call_next(request)
            try:
                REQUEST_COUNT.labels(method=request.method, endpoint=request.url.path, status=str(resp.status_code)).inc()
            except Exception:
                pass
            return resp
    except Exception:
        pass
    app.post("/v1/tasks", status_code=202)(create_task_handler)
    app.post("/v1/results")(post_results_handler)
    app.get("/v1/vms")(get_vms_handler)
    app.get("/")(ui_handler)
    # start/stop routes
    @app.post('/v1/vms/{vm_id}/start')
    def _start_vm(vm_id: str, token: Optional[str] = None, authorization: Optional[str] = Header(None)):
        # prefer Authorization: Bearer <token>
        if authorization and authorization.lower().startswith('bearer '):
            token = authorization.split(None, 1)[1]
        return start_vm_core(vm_id, token=token)

    @app.post('/v1/vms/{vm_id}/stop')
    def _stop_vm(vm_id: str, token: Optional[str] = None, authorization: Optional[str] = Header(None)):
        if authorization and authorization.lower().startswith('bearer '):
            token = authorization.split(None, 1)[1]
        return stop_vm_core(vm_id, token=token)

    @app.get('/v1/vms/{vm_id}/logs')
    def _get_logs(vm_id: str, token: Optional[str] = None):
        # no auth for logs currently
        return get_logs_core(vm_id)

    # SSE log stream (dev-friendly; will yield file contents periodically)
    try:
        from fastapi.responses import StreamingResponse
    except Exception:
        StreamingResponse = None
    @app.get('/v1/vms/{vm_id}/logs/stream')
    async def _stream_logs(vm_id: str, token: Optional[str] = None):
        # prefer using watchfiles awatch if available for efficient notifications
        if StreamingResponse is None:
            raise HTTPException(status_code=501, detail='streaming not supported')

        try:
            from watchfiles import awatch
            HAVE_WATCHFILES = True
        except Exception:
            awatch = None
            HAVE_WATCHFILES = False

        async def event_stream_watch():
            results_dir = Path(vm_mgr.config.paths.results) / vm_id
            p = results_dir / 'vm.log'
            last_size = 0
            # watch the parent directory
            parent = str(results_dir)
            async for changes in awatch(parent):
                # changes is an iterable of (change, path)
                for change, path in changes:
                    if path.endswith('vm.log'):
                        try:
                            cur = await asyncio.to_thread(lambda: p.stat().st_size if p.exists() else 0)
                            if cur > last_size:
                                def read_chunk():
                                    with open(p, 'r') as f:
                                        f.seek(last_size)
                                        return f.read()
                                chunk = await asyncio.to_thread(read_chunk)
                                if chunk:
                                    for line in chunk.splitlines():
                                        yield f"data: {line}\n\n"
                                last_size = cur
                        except Exception:
                            continue

        async def event_stream_poll():
            results_dir = Path(vm_mgr.config.paths.results) / vm_id
            p = results_dir / 'vm.log'
            last_size = 0
            try:
                while True:
                    try:
                        if p.exists():
                            cur = await asyncio.to_thread(lambda: p.stat().st_size)
                            if cur > last_size:
                                def read_chunk():
                                    with open(p, 'r') as f:
                                        f.seek(last_size)
                                        return f.read()
                                chunk = await asyncio.to_thread(read_chunk)
                                if chunk:
                                    for line in chunk.splitlines():
                                        yield f"data: {line}\n\n"
                                last_size = cur
                        await asyncio.sleep(0.5)
                    except asyncio.CancelledError:
                        break
                    except Exception:
                        await asyncio.sleep(0.5)
            except GeneratorExit:
                return

        if HAVE_WATCHFILES:
            return StreamingResponse(event_stream_watch(), media_type='text/event-stream')
        return StreamingResponse(event_stream_poll(), media_type='text/event-stream')

    # WebSocket streaming endpoint (preferred for live logs)
    try:
        from fastapi import WebSocket, WebSocketDisconnect
    except Exception:
        WebSocket = None
        WebSocketDisconnect = None

    if WebSocket is not None:
        @app.websocket('/v1/vms/{vm_id}/logs/ws')
        async def _ws_logs(websocket: WebSocket, vm_id: str):
            # simple Authorization check on websocket headers
            auth = None
            try:
                for k, v in websocket.headers:
                    if k.lower() == 'authorization':
                        auth = v
                        break
            except Exception:
                auth = None
            if not _check_token((auth.split(None,1)[1] if auth and auth.lower().startswith('bearer ') else None)):
                # refuse connection
                await websocket.close(code=1008)
                return
            await websocket.accept()
            results_dir = Path(vm_mgr.config.paths.results) / vm_id
            p = results_dir / 'vm.log'
            last_size = 0
            try:
                while True:
                    try:
                        if p.exists():
                            cur = await asyncio.to_thread(lambda: p.stat().st_size)
                            if cur > last_size:
                                def read_chunk():
                                    with open(p, 'r') as f:
                                        f.seek(last_size)
                                        return f.read()
                                chunk = await asyncio.to_thread(read_chunk)
                                if chunk:
                                    for line in chunk.splitlines():
                                        await websocket.send_text(line)
                                last_size = cur
                        await asyncio.sleep(0.5)
                    except WebSocketDisconnect:
                        break
                    except Exception:
                        await asyncio.sleep(0.5)
            finally:
                try:
                    await websocket.close()
                except Exception:
                    pass

    @app.post('/v1/token/rotate')
    def _rotate_token(token: Optional[str] = None, authorization: Optional[str] = Header(None)):
        if authorization and authorization.lower().startswith('bearer '):
            token = authorization.split(None, 1)[1]
        return {'token': rotate_token_core(token)}
