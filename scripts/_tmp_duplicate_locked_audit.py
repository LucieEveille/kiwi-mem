"""One-shot CI proof that T-S4-2 detects duplicate locked IDs without dedupe."""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "database.py"
NEEDLE = "    unique_ids = list(dict.fromkeys(ids))"
MUTATION = "    unique_ids = list(ids)"


def main() -> int:
    original = TARGET.read_bytes()
    source = original.decode("utf-8")
    if source.count(NEEDLE) != 1:
        raise RuntimeError("duplicate-ID dedupe source anchor drifted")

    try:
        TARGET.write_text(source.replace(NEEDLE, MUTATION, 1), encoding="utf-8")
        result = subprocess.run(
            [sys.executable, "scripts/test_kiwi_safety_sync.py"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        combined = f"{result.stdout}\n{result.stderr}"
        if result.returncode == 0:
            raise AssertionError("dedupe mutation escaped T-S4-2")
        if not re.search(r"'rejected': \[(\d+), \1\]", combined):
            raise AssertionError(
                "dedupe mutation turned red for an unexpected reason\n"
                + combined[-4000:]
            )
        print("PASS M-S4d: duplicate locked ID produced a duplicate rejected entry")
        return 0
    finally:
        TARGET.write_bytes(original)
        if TARGET.read_bytes() != original:
            raise RuntimeError("database.py was not restored byte-for-byte")


if __name__ == "__main__":
    raise SystemExit(main())
