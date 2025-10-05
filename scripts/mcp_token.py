#!/usr/bin/env python3
"""CLI helper for MCP auth token.

Usage:
  python scripts/mcp_token.py show         # prints token from MCP_AUTH_FILE or MCP_AUTH_TOKEN
  python scripts/mcp_token.py rotate-local # rotate token locally (write new token to file)
  python scripts/mcp_token.py rotate-remote http://host:port  # call /v1/token/rotate with current token in Authorization header

This script intentionally has no external dependencies.
"""
import os
import sys
import secrets
import urllib.request
import json
from pathlib import Path

MCP_AUTH_FILE = os.getenv('MCP_AUTH_FILE', '.mcp_token')


def read_token():
    env = os.getenv('MCP_AUTH_TOKEN')
    if env:
        return env
    p = Path(MCP_AUTH_FILE)
    if p.exists():
        return p.read_text().strip()
    return ''


def write_token(t):
    try:
        p = Path(MCP_AUTH_FILE)
        # atomic write
        import tempfile, os
        td = tempfile.NamedTemporaryFile(delete=False, dir=str(p.parent) if p.parent.exists() else None)
        try:
            td.write(t.encode('utf-8'))
            td.flush(); td.close()
            os.replace(td.name, str(p))
            try:
                p.chmod(0o600)
            except Exception:
                pass
            return True
        finally:
            try:
                if os.path.exists(td.name):
                    os.remove(td.name)
            except Exception:
                pass
    except Exception as e:
        print('failed to write token:', e, file=sys.stderr)
        return False


def rotate_local():
    new = secrets.token_urlsafe(24)
    if write_token(new):
        print(new)
        return 0
    return 2


def rotate_remote(url):
    cur = read_token()
    if not cur:
        print('no current token available to authenticate to remote', file=sys.stderr)
        return 2
    if not url.startswith('http'):
        url = 'http://' + url
    api = url.rstrip('/') + '/v1/token/rotate'
    req = urllib.request.Request(api, method='POST')
    req.add_header('Authorization', 'Bearer ' + cur)
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            body = r.read().decode('utf-8')
            try:
                j = json.loads(body)
                if 'token' in j:
                    print(j['token'])
                    return 0
                print(body)
                return 1
            except Exception:
                print(body)
                return 1
    except Exception as e:
        print('remote rotate failed:', e, file=sys.stderr)
        return 2


def usage():
    print(__doc__)


def main(argv):
    if len(argv) < 2:
        usage(); return 1
    cmd = argv[1]
    if cmd == 'show':
        print(read_token())
        return 0
    if cmd == 'rotate-local':
        return rotate_local()
    if cmd == 'rotate-remote':
        if len(argv) < 3:
            print('need url for rotate-remote', file=sys.stderr); return 2
        return rotate_remote(argv[2])
    usage(); return 1


if __name__ == '__main__':
    sys.exit(main(sys.argv))
