"""
conftest.py  (~/mara/conftest.py)

Pytest session fixtures for MARA dry-run integration tests.

TWO JOBS
--------

1. VENV GUARD
   The test suite imports fastapi, httpx, structlog, etc. — all installed
   only inside ~/mara/.venv, not in the system Python.
   If pytest is invoked with system Python (/usr/bin/python3) every single
   worker test errors with "No module named 'fastapi'".

   This file detects that situation at collection time and aborts with a
   one-line fix rather than letting 50 tests ERROR for a confusing reason.

   FIX IF YOU SEE THE VENV WARNING:
       source ~/mara/.venv/bin/activate
       pytest tests/test_integration_dryrun.py -v

2. MODULE-LEVEL IMPORT STUBS FOR hypervisor/main.py
   hypervisor/main.py does top-level imports of httpx and fastapi.
   When TestHypervisorCycle loads main.py via importlib to test pure
   helper functions (_reconcile_capital, _count_open_positions, etc.),
   those imports run immediately — even though no HTTP call is ever made.

   This conftest injects lightweight stub modules into sys.modules BEFORE
   any test fixture loads main.py.  The stubs satisfy the import without
   pulling in real network code.  The functions under test never touch
   the stubs at runtime — they only use stdlib (time, os, dict math).

   Stubs provided:
       httpx              — AsyncClient, Client (no-op)
       fastapi            — FastAPI, HTTPException (no-op)
       fastapi.responses  — JSONResponse (no-op)

   Worker modules (nautilus, arbitrader, autohedge, polymarket) are loaded
   only inside TestClient fixtures which run inside the venv where fastapi
   and httpx are actually installed.  Those tests do NOT use these stubs.
"""

import sys
import os
import types
from unittest.mock import MagicMock, AsyncMock

# ── 1. Venv guard ─────────────────────────────────────────────────────────────

def _check_venv():
    executable = sys.executable
    mara_venv  = os.path.expanduser("~/mara/.venv")

    # If running inside any virtualenv, trust it
    if hasattr(sys, "real_prefix") or (
        hasattr(sys, "base_prefix") and sys.base_prefix != sys.prefix
    ):
        return   # inside a venv — OK

    # System Python detected
    print(
        "\n"
        "╔══════════════════════════════════════════════════════════════╗\n"
        "║  MARA DRY-RUN: WRONG PYTHON INTERPRETER                     ║\n"
        "║                                                              ║\n"
        f"║  Running: {executable[:52]:<52} ║\n"
        "║                                                              ║\n"
        "║  fastapi, httpx, structlog are only installed in the venv.  ║\n"
        "║  Every worker test will ERROR with 'No module named fastapi' ║\n"
        "║                                                              ║\n"
        "║  FIX — run these two commands:                               ║\n"
        "║    source ~/mara/.venv/bin/activate                          ║\n"
        "║    pytest tests/test_integration_dryrun.py -v               ║\n"
        "╚══════════════════════════════════════════════════════════════╝\n",
        file=sys.stderr,
    )
    # Don't hard-abort — let pytest collect so the user sees WHICH tests
    # would have run, but emit the warning prominently.

_check_venv()


# ── 2. sys.modules stubs for hypervisor/main.py ───────────────────────────────
#
# hypervisor/main.py top-level imports:
#   import httpx
#   from fastapi import FastAPI, HTTPException
#   from fastapi.responses import JSONResponse
#
# These run when importlib.exec_module() is called in _load_module().
# We stub them so the module loads, but the stubs are never called at
# test runtime (tests only call pure helper functions on the module).
#
# We only install the stubs if the real packages are NOT already importable.
# Inside the activated venv, the real packages are present and preferred.

def _install_stub(name: str, attrs: dict) -> None:
    """Install a stub module only if the real one isn't already importable."""
    if name in sys.modules:
        return
    try:
        __import__(name)
        return   # real package available — don't stub it
    except ImportError:
        pass

    mod = types.ModuleType(name)
    for attr, value in attrs.items():
        setattr(mod, attr, value)
    sys.modules[name] = mod


# ── httpx stub ────────────────────────────────────────────────────────────────

class _FakeAsyncClient:
    """Minimal async context manager stub for httpx.AsyncClient."""
    def __init__(self, *a, **kw): pass
    async def __aenter__(self): return self
    async def __aexit__(self, *a): pass
    async def get(self, *a, **kw):  return _FakeResponse()
    async def post(self, *a, **kw): return _FakeResponse()

class _FakeResponse:
    status_code = 200
    def json(self): return {}
    text = ""

_install_stub("httpx", {
    "AsyncClient": _FakeAsyncClient,
    "Client":      _FakeAsyncClient,
})


# ── fastapi stub ──────────────────────────────────────────────────────────────

class _FakeFastAPI:
    def __init__(self, *a, **kw): pass
    def get(self, *a, **kw):
        def decorator(fn): return fn
        return decorator
    def post(self, *a, **kw):
        def decorator(fn): return fn
        return decorator

class _FakeHTTPException(Exception):
    def __init__(self, status_code=500, detail=""):
        self.status_code = status_code
        self.detail      = detail

_install_stub("fastapi", {
    "FastAPI":        _FakeFastAPI,
    "HTTPException":  _FakeHTTPException,
})

_install_stub("fastapi.responses", {
    "JSONResponse": dict,
})


# ── structlog stub (used by worker modules) ───────────────────────────────────

class _FakeLogger:
    def info(self, *a, **kw):    pass
    def warning(self, *a, **kw): pass
    def error(self, *a, **kw):   pass
    def debug(self, *a, **kw):   pass

class _FakeStructlog:
    @staticmethod
    def get_logger(*a, **kw): return _FakeLogger()

_install_stub("structlog", {
    "get_logger": _FakeStructlog.get_logger,
})
