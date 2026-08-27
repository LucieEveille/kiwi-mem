#!/usr/bin/env python3
"""Read-only W2-05 event-ledger reconciliation CLI."""

from __future__ import annotations

import argparse
import asyncio
import io
import json
import sys
from contextlib import redirect_stdout
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Audit the event ledger without writing it")
    parser.add_argument("--json", action="store_true", dest="as_json")
    parser.add_argument("--session")
    parser.add_argument("--sample-limit", type=int, default=50)
    return parser


async def _run(args) -> dict:
    import database

    try:
        return await database.reconcile_event_ledger(
            session_id=args.session,
            sample_limit=args.sample_limit,
        )
    finally:
        await database.close_pool()


def main(argv=None) -> int:
    parser = _parser()
    try:
        args = parser.parse_args(argv)
        if not 1 <= args.sample_limit <= 500:
            raise ValueError
    except (SystemExit, ValueError):
        return 64

    captured = io.StringIO()
    try:
        with redirect_stdout(captured):
            result = asyncio.run(_run(args))
    except ValueError:
        return 64

    if args.as_json:
        print(json.dumps(result, sort_keys=True, ensure_ascii=True, separators=(",", ":")))
    else:
        print(json.dumps({
            "ok": result["ok"],
            "total_rows": result["total_rows"],
            "unexplained": sum(
                bucket["count"] for bucket in result["unexplained"].values()),
        }, sort_keys=True, ensure_ascii=True, separators=(",", ":")))
    return 0 if result["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
