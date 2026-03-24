#!/usr/bin/env python3
"""
Run from ~/mara:
    python3 patch_capital_float.py

Uses line-number surgery instead of string matching to avoid Unicode
box-drawing character issues in the comment lines.
"""
import os

ROOT = os.path.expanduser("~/mara")
path = f"{ROOT}/hypervisor/allocator/capital.py"

with open(path) as f:
    lines = f.readlines()

# Find the target lines by content (not the unicode comment)
start = None
end   = None
for i, line in enumerate(lines):
    if "total_weight = sum(eligible.values())" in line:
        start = i
    if start and 'result.cash_reserve = round(self.total_capital - sum(allocations.values()), 2)' in line:
        end = i
        break

assert start is not None, "Could not find 'total_weight = sum(eligible.values())'"
assert end   is not None, "Could not find cash_reserve line"

print(f"Replacing lines {start+1}–{end+1}")

replacement = """\
        # Round all workers except the last to 2 d.p., then give the last
        # worker the exact remainder of max_deployable. This eliminates the
        # N * $0.005 rounding accumulation that otherwise appears as phantom
        # cash or phantom capital across cycles.
        # Cash is exactly total_capital - max_deployable (the regime reserve)
        # — never a rounding residual.
        total_weight  = sum(eligible.values())
        worker_list   = list(eligible.keys())
        allocations: Dict[str, float] = {}

        running = 0.0
        for worker in worker_list[:-1]:
            amt = round(max_deploy * (eligible[worker] / total_weight), 2)
            allocations[worker] = amt
            running += amt
        # Last worker absorbs any rounding residual — keeps deployed == max_deploy
        last = worker_list[-1]
        allocations[last] = round(max_deploy - running, 2)

        result.allocations  = allocations
        # Cash is the regime reserve fraction, never a rounding residual
        result.cash_reserve = round(self.total_capital - max_deploy, 2)
"""

new_lines = lines[:start] + [replacement] + lines[end + 1:]

with open(path, "w") as f:
    f.writelines(new_lines)

print("✅ capital.py float fix applied")

# Sanity check
with open(path) as f:
    src = f.read()
assert "worker_list   = list(eligible.keys())" in src, "Patch not found after write"
assert "result.cash_reserve = round(self.total_capital - max_deploy, 2)" in src
print("✅ Sanity check passed")
print()
print("Now run:")
print("  docker compose build --no-cache hypervisor")
print("  docker compose up -d")
