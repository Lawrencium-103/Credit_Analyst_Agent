"""Vercel entrypoint.

Vercel resolves the ``tool.vercel.entrypoint`` module path to a file relative to
the project root, so it cannot find ``src/credit_agent/api/app.py``. This thin
file sits at the repo root, puts ``src`` on the path, and re-exports the FastAPI
``app`` from the package.

If the app fails to import (e.g. a missing dependency at cold start), we still
expose an ASGI app that returns JSON — so the SPA gets a parseable error instead
of Vercel's HTML error page. The fallback is written with raw ASGI so it does
not depend on starlette being installed.
"""

import json
import os
import sys
import traceback

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))

try:
    from credit_agent.api.app import app  # noqa: E402,F401
except Exception:  # pragma: no cover - defensive
    _error = traceback.format_exc()
    _headers = [(b"content-type", b"application/json")]

    async def app(scope, receive, send):
        if scope["type"] == "lifespan":
            return
        body = json.dumps({"error": "import_failed", "detail": _error}).encode("utf-8")
        await send({"type": "http.response.start", "status": 500, "headers": _headers})
        await send({"type": "http.response.body", "body": body})
