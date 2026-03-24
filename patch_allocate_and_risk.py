#!/usr/bin/env python3
"""
Run from ~/mara:
    python3 patch_allocate_and_risk.py

Fixes:
  1. manager.py   — nautilus 100% drawdown on cold start (no entry_capital guard)
  2. polymarket   — missing POST /allocate endpoint (404)
  3. autohedge    — missing POST /allocate endpoint (404)
  4. .env         — BYBIT_REST and CYCLE_INTERVAL_SEC merged on one line (missing newline)
"""
import re, sys, os

ROOT = os.path.expanduser("~/mara")

# ── Fix 1: manager.py — skip per-worker drawdown until capital is allocated ──
print("Fix 1: manager.py cold-start drawdown guard...")
path = f"{ROOT}/hypervisor/risk/manager.py"
with open(path) as f:
    src = f.read()

old = (
    "            dd = state.drawdown_pct()\n"
    "            if dd > WORKER_MAX_DRAWDOWN_PCT:\n"
    "                return RiskVerdict(\n"
    "                    safe            = False,\n"
    "                    reason          = (\n"
    "                        f\"Worker {worker} drawdown {dd*100:.1f}% \"\n"
    "                        f\"exceeds per-worker limit {WORKER_MAX_DRAWDOWN_PCT*100:.0f}%\"\n"
    "                    ),\n"
    "                    action          = \"halt_worker\",\n"
    "                    affected_worker = worker,\n"
    "                )"
)
new = (
    "            # Skip drawdown gate until capital has been formally allocated.\n"
    "            # entry_capital=0 means record_worker_allocation() hasn't been called yet\n"
    "            # (first cycle cold-start). Without this guard every fresh worker shows\n"
    "            # 100% drawdown because peak_capital defaults to entry_capital=0.\n"
    "            if state.entry_capital <= 0:\n"
    "                continue\n"
    "            dd = state.drawdown_pct()\n"
    "            if dd > WORKER_MAX_DRAWDOWN_PCT:\n"
    "                return RiskVerdict(\n"
    "                    safe            = False,\n"
    "                    reason          = (\n"
    "                        f\"Worker {worker} drawdown {dd*100:.1f}% \"\n"
    "                        f\"exceeds per-worker limit {WORKER_MAX_DRAWDOWN_PCT*100:.0f}%\"\n"
    "                    ),\n"
    "                    action          = \"halt_worker\",\n"
    "                    affected_worker = worker,\n"
    "                )"
)
assert old in src, "Fix 1: target string not found in manager.py"
with open(path, "w") as f:
    f.write(src.replace(old, new, 1))
print("  ✅ manager.py patched")


# ── Fix 2: polymarket adapter — add POST /allocate ───────────────────────────
print("Fix 2: polymarket /allocate endpoint...")
path = f"{ROOT}/workers/polymarket/adapter/main.py"
with open(path) as f:
    src = f.read()

# Add allocated_usd field to AdapterState.__init__
old = (
    "    async def start_bot(self, regime: str):"
)
new = (
    "    allocated_usd: float = 0.0\n\n"
    "    async def start_bot(self, regime: str):"
)
assert old in src, "Fix 2a: AdapterState.start_bot anchor not found"
src = src.replace(old, new, 1)

# Add /allocate endpoint before /pause
old = "@app.post(\"/pause\")\nasync def pause():"
new = (
    "@app.post(\"/allocate\")\n"
    "async def allocate(body: dict):\n"
    "    \"\"\"Receive capital allocation from Hypervisor.\"\"\"\n"
    "    amount = float(body.get(\"amount_usd\", 0.0))\n"
    "    state.allocated_usd = amount\n"
    "    logger.info(\"polymarket_allocated\", amount_usd=amount,\n"
    "                paper=body.get(\"paper_trading\", True))\n"
    "    return {\"status\": \"ok\", \"worker\": WORKER_NAME, \"allocated_usd\": amount}\n"
    "\n\n"
    "@app.post(\"/pause\")\n"
    "async def pause():"
)
assert old in src, "Fix 2b: /pause anchor not found in polymarket main.py"
src = src.replace(old, new, 1)

# Also fix /metrics to return Response not bare string
if 'from fastapi.responses import Response' not in src:
    src = src.replace(
        'from fastapi import FastAPI',
        'from fastapi import FastAPI\nfrom fastapi.responses import Response'
    )
old_metrics = (
    "    return (\n"
    "        f'mara_worker_active{{worker=\"polymarket\"}} {active}\\n'\n"
    "        f'mara_polymarket_exposure_usd {exposure:.4f}\\n'\n"
    "        f'mara_polymarket_pnl_usd {pnl:.4f}\\n'\n"
    "        f'mara_polymarket_skew {state.get_skew():.4f}\\n'\n"
    "    )"
)
new_metrics = (
    "    content = (\n"
    "        f'mara_worker_active{{worker=\"polymarket\"}} {active}\\n'\n"
    "        f'mara_polymarket_exposure_usd {exposure:.4f}\\n'\n"
    "        f'mara_polymarket_pnl_usd {pnl:.4f}\\n'\n"
    "        f'mara_polymarket_skew {state.get_skew():.4f}\\n'\n"
    "    )\n"
    "    return Response(content=content, media_type=\"text/plain\")"
)
if old_metrics in src:
    src = src.replace(old_metrics, new_metrics, 1)

with open(path, "w") as f:
    f.write(src)
print("  ✅ polymarket/adapter/main.py patched")


# ── Fix 3: autohedge worker_api.py — add POST /allocate ─────────────────────
print("Fix 3: autohedge /allocate endpoint...")
path = f"{ROOT}/workers/autohedge/worker_api.py"
with open(path) as f:
    src = f.read()

# Check if /allocate already exists
if '"/allocate"' in src or "'/allocate'" in src:
    print("  ⏭  autohedge already has /allocate, skipping")
else:
    # Find /pause to insert before it
    anchor = '@app.post("/pause")'
    if anchor not in src:
        anchor = "@app.post('/pause')"
    assert anchor in src, "Fix 3: /pause anchor not found in autohedge worker_api.py"

    new_endpoint = (
        '@app.post("/allocate")\n'
        'async def allocate(body: dict):\n'
        '    """Receive capital allocation from Hypervisor."""\n'
        '    amount = float(body.get("amount_usd", 0.0))\n'
        '    state.allocated_usd = amount\n'
        '    return {"status": "ok", "worker": "autohedge", "allocated_usd": amount}\n'
        '\n\n'
    )
    src = src.replace(anchor, new_endpoint + anchor, 1)

    # Ensure state has allocated_usd field
    if "allocated_usd" not in src:
        # Add to wherever state is initialised — find the state class or dict
        old_state = 'self.paused: bool = False'
        if old_state in src:
            src = src.replace(
                old_state,
                old_state + '\n        self.allocated_usd: float = 0.0'
            )

    with open(path, "w") as f:
        f.write(src)
    print("  ✅ autohedge/worker_api.py patched")


# ── Fix 4: .env — fix merged BYBIT_REST + CYCLE_INTERVAL_SEC line ────────────
print("Fix 4: .env missing newline before CYCLE_INTERVAL_SEC...")
path = f"{ROOT}/.env"
with open(path) as f:
    src = f.read()

# The corrupted line looks like: BYBIT_REST=https://api.bybit.comCYCLE_INTERVAL_SEC=60
if "BYBIT_REST=https://api.bybit.comCYCLE_INTERVAL_SEC" in src:
    src = src.replace(
        "BYBIT_REST=https://api.bybit.comCYCLE_INTERVAL_SEC=",
        "BYBIT_REST=https://api.bybit.com\nCYCLE_INTERVAL_SEC="
    )
    with open(path, "w") as f:
        f.write(src)
    print("  ✅ .env fixed — CYCLE_INTERVAL_SEC is now its own line")
elif "CYCLE_INTERVAL_SEC" in src:
    print("  ⏭  .env looks fine already, CYCLE_INTERVAL_SEC exists as separate line")
else:
    # Add it
    with open(path, "a") as f:
        f.write("\nCYCLE_INTERVAL_SEC=60\n")
    print("  ✅ .env — added CYCLE_INTERVAL_SEC=60")


print("\nAll patches applied. Now run:")
print("  docker compose build --no-cache hypervisor worker-polymarket worker-autohedge")
print("  docker compose up -d")
print("  docker compose logs -f hypervisor 2>&1 | grep -v 'GET /health'")
