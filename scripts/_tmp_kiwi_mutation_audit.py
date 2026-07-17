#!/usr/bin/env python3
"""One-shot mutation audit for the approved kiwi safety-sync batch.

This file is intentionally temporary: CI runs it once to prove that the
permanent PostgreSQL guards reject the required regressions, then the delivery
branch removes it before second-track review.
"""

from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TARGETS = ("database.py", "main.py", "memory_extractor.py")
BASE = {name: (ROOT / name).read_bytes() for name in TARGETS}


@dataclass(frozen=True)
class Mutation:
    name: str
    path: str
    old: str
    new: str
    expected: str
    count: int = 1


MUTATIONS = (
    Mutation(
        "M-S1 settings whitelist short-circuit",
        "main.py",
        """            if key not in SYNC_SETTING_KEYS:
                rejected.append(key)
                continue
""",
        """            if False and key not in SYNC_SETTING_KEYS:
                rejected.append(key)
                continue
""",
        "wrong updated set",
    ),
    Mutation(
        "M-S2a memory title/content log",
        "database.py",
        """    return new_id


async def delete_memory""",
        """    print(content, title)
    return new_id


async def delete_memory""",
        "memory log leaked content",
    ),
    Mutation(
        "M-S2b extraction text[:200] log",
        "memory_extractor.py",
        """            text = text.strip()
            if text.startswith("```json")""",
        """            print(text[:200])
            text = text.strip()
            if text.startswith("```json")""",
        "raw extraction response leaked",
    ),
    Mutation(
        "M-S3 UTC/local calendar anchor",
        "database.py",
        "today = datetime.now(TZ_CST).date()",
        "today = datetime.now().date()",
        "calendar anchor did not request TZ_CST",
    ),
    Mutation(
        "M-S4a remove locked-memory condition",
        "database.py",
        "AND (COALESCE(is_permanent, FALSE) = FALSE OR $2)",
        "AND TRUE",
        "in test_s4",
        count=2,
    ),
    Mutation(
        "M-S4b JSON bool coercion",
        "main.py",
        'force = body.get("force") is True',
        'force = bool(body.get("force"))',
        "force variant penetrated",
    ),
    Mutation(
        "M-S4c remove clear confirmation gate",
        "main.py",
        '''body.get("force") is True
            and body.get("confirm") == "DELETE_ALL_MEMORIES"''',
        'body.get("force") is True',
        "invalid clear gate passed",
    ),
    Mutation(
        "M-S5a bare DELETE substring helper",
        "database.py",
        """    try:
        return int(status.split()[-1]) > 0
    except (AttributeError, IndexError, TypeError, ValueError):
        return False
""",
        """    return "DELETE" in status if status is not None else False
""",
        "rowcount mismatch",
    ),
    Mutation(
        "M-S5b gateway malformed-tag helper",
        "database.py",
        """    try:
        return int(status.split()[-1]) > 0
    except (AttributeError, IndexError, TypeError, ValueError):
        return False
""",
        """    try:
        return status.split()[-1] != "0"
    except (AttributeError, IndexError, TypeError, ValueError):
        return False
""",
        "DELETE nope",
    ),
    Mutation(
        "M-S5c real conversation caller bypass",
        "database.py",
        "return _rowcount_nonzero(result)",
        'return "DELETE" in result',
        "in test_s5",
    ),
    Mutation(
        "M-S6a hard-delete Dream log",
        "main.py",
        """                    UPDATE dream_logs
                    SET deleted = TRUE
                    WHERE id = $1 AND NOT deleted
                    RETURNING id
""",
        """                    DELETE FROM dream_logs
                    WHERE id = $1 AND NOT deleted
                    RETURNING id
""",
        "in test_s6",
    ),
    Mutation(
        "M-S6b allow late update of deleted Dream",
        "database.py",
        'sql = f"UPDATE dream_logs SET {\', \'.join(sets)} WHERE id = ${idx} AND NOT deleted"',
        'sql = f"UPDATE dream_logs SET {\', \'.join(sets)} WHERE id = ${idx}"',
        "in test_s6",
    ),
)


def restore() -> None:
    for name, data in BASE.items():
        (ROOT / name).write_bytes(data)


def apply_mutation(mutation: Mutation) -> None:
    path = ROOT / mutation.path
    text = path.read_text(encoding="utf-8")
    found = text.count(mutation.old)
    if found < mutation.count:
        raise RuntimeError(
            f"{mutation.name}: expected at least {mutation.count} source matches, found {found}"
        )
    path.write_text(
        text.replace(mutation.old, mutation.new, mutation.count),
        encoding="utf-8",
        newline="\n",
    )


def run_mutation(mutation: Mutation) -> None:
    restore()
    apply_mutation(mutation)
    env = os.environ.copy()
    completed = subprocess.run(
        [sys.executable, "scripts/test_kiwi_safety_sync.py"],
        cwd=ROOT,
        env=env,
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=180,
    )
    output = completed.stdout
    if completed.returncode == 0:
        raise AssertionError(f"{mutation.name}: permanent suite stayed green")
    if mutation.expected not in output:
        tail = "\n".join(output.splitlines()[-50:])
        raise AssertionError(
            f"{mutation.name}: red for an unexpected reason; missing {mutation.expected!r}\n{tail}"
        )
    print(f"PASS {mutation.name}: expected red captured ({mutation.expected})")


def main() -> int:
    try:
        for mutation in MUTATIONS:
            run_mutation(mutation)
    finally:
        restore()
    subprocess.run(
        ["git", "diff", "--exit-code", "--", *TARGETS],
        cwd=ROOT,
        check=True,
    )
    print(f"PASS: {len(MUTATIONS)} temporary mutations all red; formal source restored")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
