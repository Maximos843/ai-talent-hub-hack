"""Canonical entrypoint for the Talent Interview MVP.

Run this project with either:

    uvicorn main:app --host 0.0.0.0 --port 8000

or simply:

    python main.py

The original business application lives in ``legacy_main.py``.  ``app.py``
wraps it with the current auth/session/proctoring gateway.  The small import
compatibility below lets ``app.py`` still import ``main`` while it is being
constructed, but users no longer need to know about that implementation detail.
"""
from __future__ import annotations

import sys

from legacy_main import _manager_can_view
from legacy_main import app as _legacy_app

# app.py historically imports ``main`` as its legacy business module.  When
# app.py itself is being imported, expose that legacy surface and do not recurse
# back into app.py.  On a normal ``import main`` / ``uvicorn main:app`` we then
# replace ``app`` with the complete gateway application.
app = _legacy_app

if "app" not in sys.modules:
    from app import app as app


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=False)
