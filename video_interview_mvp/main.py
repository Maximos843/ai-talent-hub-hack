"""Canonical entrypoint for the Talent Interview MVP.

Run with either:

    uvicorn main:app --host 0.0.0.0 --port 8000

or simply:

    python main.py

The original business application lives in ``legacy_main.py``. ``app.py``
wraps it with auth/session/proctoring. Users only need to know about main.py.
"""
from __future__ import annotations

import sys

from legacy_main import _manager_can_view
from legacy_main import app as _legacy_app

app = _legacy_app

# app.py imports ``main`` while constructing the gateway. In that case expose
# only the legacy surface to avoid recursion. On a normal ``import main`` we
# replace it with the complete gateway app.
if "app" not in sys.modules:
    from app import app as app


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
