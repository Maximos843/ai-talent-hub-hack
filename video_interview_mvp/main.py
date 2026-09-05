"""Canonical entrypoint for the Talent Interview MVP.

Run this project with either:

    uvicorn main:app --host 0.0.0.0 --port 8000

or simply:

    python main.py

The original business application lives in ``legacy_main.py``. ``app.py``
wraps it with the current auth/session/proctoring gateway. Users do not need to
know about that internal split.
"""
from __future__ import annotations

import sys

from legacy_main import _manager_can_view
from legacy_main import app as _legacy_app

# app.py historically imports ``main`` as its legacy business module. When
# app.py itself is being imported, expose that legacy surface and do not recurse
# back into app.py. On a normal ``import main`` / ``uvicorn main:app`` we replace
# ``app`` with the complete gateway application below.
app = _legacy_app

if "app" not in sys.modules:
    from app import app as app


if __name__ == "__main__":
    import uvicorn

    # Pass the already-built gateway object. Using the string "main:app" here
    # would import main a second time when this file is executed as __main__.
    uvicorn.run(app, host="0.0.0.0", port=8000)
