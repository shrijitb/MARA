#!/usr/bin/env python3
"""
Run from ~/mara:
    python3 patch_risk_and_status.py

Fixes:
  1. manager.py   — peak_capital updated by risk loop from /status data,
                    out-of-sync with entry_capital → false 85% drawdown.
                    Fix: remove peak update from Check 7, let only
                    record_worker_allocation control peak_capital.

  2. autohedge    — /status missing pnl, sharpe, allocated_usd fields.
                    Hypervisor defaults all to 0.0, corrupting risk state.
"""
import os

ROOT = os.path.expanduser("~/mara")

# ── Fix 1: manager.py — remove peak_capital update from Check 7 ──────────────
print("Fix 1: manager.py — remove peak_capital update from risk loop...")
path = f"{ROOT}/hypervisor/risk/manager.py"
with open(path) as f:
    src = f.read()

old = (
    "            state.current_pnl  = pnl\n"
    "            allocated          = worker_allocated.get(worker, state.entry_capital)\n"
    "            if allocated > state.peak_capital:\n"
    "                state.peak_capital = allocated\n"
    "            state.last_updated = time.time()"
)
new = (
    "            state.current_pnl  = pnl\n"
    "            # Do NOT update peak_capital here from /status data.\n"
    "            # peak_capital is authoritative only when set by record_worker_allocation().\n"
    "            # Updating it here from worker_allocated (/status responses) causes\n"
    "            # out-of-sync state: peak rises but entry_capital doesn't, producing\n"
    "            # false drawdown readings on workers with no active positions.\n"
    "            state.last_updated = time.time()"
)
assert old in src, "Fix 1: target string not found in manager.py"
with open(path, "w") as f:
    f.write(src.replace(old, new, 1))
print("  ✅ manager.py patched")


# ── Fix 2: autohedge worker_api.py — add missing fields to /status ───────────
print("Fix 2: autohedge /status — add pnl, sharpe, allocated_usd...")
path = f"{ROOT}/workers/autohedge/worker_api.py"
with open(path) as f:
    src = f.read()

old = (
    '        "uptime_s":          round(state.uptime_seconds(), 1),\n'
    '        "advisory_only":     True,\n'
    '    }'
)
new = (
    '        "uptime_s":          round(state.uptime_seconds(), 1),\n'
    '        "advisory_only":     True,\n'
    '        # Required by hypervisor for risk/sharpe tracking\n'
    '        "pnl":               0.0,\n'
    '        "sharpe":            0.0,\n'
    '        "allocated_usd":     getattr(state, "allocated_usd", 0.0),\n'
    '        "open_positions":    0,\n'
    '    }'
)
assert old in src, "Fix 2: /status return block not found in worker_api.py"
with open(path, "w") as f:
    f.write(src.replace(old, new, 1))
print("  ✅ autohedge/worker_api.py patched")


print("\nAll patches applied. Now run:")
print("  docker compose build --no-cache hypervisor worker-autohedge")
print("  docker compose up -d")
print("  docker compose logs -f hypervisor 2>&1 | grep -v 'GET /health'")
