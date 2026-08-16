"""Vercel entrypoint.

Vercel resolves the ``tool.vercel.entrypoint`` module path to a file relative to
the project root, so it cannot find ``src/credit_agent/api/app.py``. This thin
file sits at the repo root, puts ``src`` on the path, and re-exports the FastAPI
``app`` from the package.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))

from credit_agent.api.app import app  # noqa: E402,F401

__all__ = ["app"]
