"""Vercel entry point: Vercel's Python runtime serves the ASGI app exported here.

vercel.json rewrites every address to this one function and passes the address the visitor opened as `__path`
in the query string, because the function itself only sees /api/index. This wrapper puts that address back,
so the routes see '/', '/static/app.js', '/api/...' as usual."""
import sys
from pathlib import Path
from urllib.parse import parse_qsl, unquote, urlencode

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.app import app as _app  # noqa: E402

_PREFIX = "/api/index"


def _restore(scope):
    path = scope.get("path") or "/"
    qs = (scope.get("query_string") or b"").decode("latin-1")
    pairs = parse_qsl(qs, keep_blank_values=True)
    forwarded = [v for k, v in pairs if k == "__path"]
    if forwarded:
        path = "/" + unquote(forwarded[0]).lstrip("/")
        qs = urlencode([(k, v) for k, v in pairs if k != "__path"])
    elif path == _PREFIX or path.startswith(_PREFIX + "/"):
        path = path[len(_PREFIX):] or "/"
    else:
        return scope
    return dict(scope, path=path, raw_path=path.encode(), query_string=qs.encode("latin-1"))


async def app(scope, receive, send):
    if scope.get("type") in ("http", "websocket"):
        scope = _restore(scope)
    await _app(scope, receive, send)
