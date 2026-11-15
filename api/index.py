"""Vercel entry point: Vercel's Python runtime serves the ASGI app exported here.
vercel.json routes every path (pages, static files and the API) to this function."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.app import app as _app  # noqa: E402

_PREFIX = "/api/index"


async def app(scope, receive, send):
    """Undo the rewrite if the platform hands over the function's own path (/api/index/...) instead of the address
    the visitor opened, so the routes see '/', '/static/app.js', '/api/...' as usual."""
    if scope.get("type") in ("http", "websocket"):
        path = scope.get("path") or "/"
        if path == _PREFIX or path.startswith(_PREFIX + "/"):
            new = path[len(_PREFIX):] or "/"
            scope = dict(scope, path=new, raw_path=new.encode())
    await _app(scope, receive, send)
