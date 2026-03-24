#!/usr/bin/env python3
"""
Run from ~/mara:
    python3 patch_health_and_dxy.py
"""
import re, sys

# ── Patch 1: hypervisor/main.py — concurrent health check ─────────────────
HYP = "/home/shrijit/mara/hypervisor/main.py"
with open(HYP) as f:
    src = f.read()

# Find the function regardless of minor whitespace drift
pattern = re.compile(
    r'async def _check_worker_health\(\):.*?'
    r'(?=\nasync def |\nclass |\n@app\.)',
    re.DOTALL
)
m = pattern.search(src)
if not m:
    print("ERROR: _check_worker_health not found in main.py — print the function:")
    for i, line in enumerate(src.split("\n"), 1):
        if "health" in line.lower() and "check" in line.lower():
            print(f"  {i}: {line}")
    sys.exit(1)

old_fn = m.group(0)
new_fn = '''async def _check_worker_health():
    """Ping every registered worker /health endpoint concurrently."""
    workers = list(WORKER_REGISTRY.keys())
    urls    = [WORKER_REGISTRY[w] for w in workers]
    async with httpx.AsyncClient(timeout=WORKER_TIMEOUT_SEC) as client:
        results = await asyncio.gather(
            *[client.get(f"{url}/health") for url in urls],
            return_exceptions=True,
        )
    for worker, result in zip(workers, results):
        if isinstance(result, Exception):
            state.worker_health[worker] = False
            logger.warning(f"  {worker}: health check failed ({type(result).__name__}: {result})")
        else:
            ok = result.status_code == 200
            state.worker_health[worker] = ok
            if not ok:
                logger.warning(f"  {worker}: health returned HTTP {result.status_code}")

'''

src = src.replace(old_fn, new_fn, 1)
with open(HYP, "w") as f:
    f.write(src)
print("✅  hypervisor/main.py — _check_worker_health patched")

# ── Patch 2: data/feeds/market_data.py — DXY fallback ticker ──────────────
MKT = "/home/shrijit/mara/data/feeds/market_data.py"
with open(MKT) as f:
    src = f.read()

old_dxy = 'df = yf.download("DX-Y.NYB", period="5d", progress=False, auto_adjust=True)'
new_dxy = '''\
for _ticker in ("DX-Y.NYB", "DX=F"):
            try:
                df = yf.download(_ticker, period="5d", progress=False, auto_adjust=True)
                if not df.empty:
                    break
            except Exception:
                df = None
        if df is None:
            df = type("_E", (), {"empty": True})()'''

if old_dxy not in src:
    print("ERROR: DXY download line not found — check market_data.py line 148")
    sys.exit(1)

src = src.replace(old_dxy, new_dxy, 1)
with open(MKT, "w") as f:
    f.write(src)
print("✅  data/feeds/market_data.py — DXY fallback ticker patched")

print("\nDone. Now run:")
print("  docker compose restart hypervisor")
print("  docker compose logs -f hypervisor")
