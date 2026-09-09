#!/usr/bin/env python3
"""PREP-01 knife inventory only: implementation anchors follow the green commit.

No mutation results exist at the tests-first stage. --list is read-only;
execution refuses to produce a ledger until real anchors are implemented.
"""
import argparse
import json

KNIVES = [
    (1, "02", "Count IP literal as foreign"),
    (2, "02", "Persist or log Host"),
    (3, "01", "Return an extra last_host field"),
    (4, "01", "Claim protection is enabled"),
    (5, "01", "Accept wildcard hostname"),
    (6, "03", "Reject body in observation wrapper"),
    (7, "PG-01", "Remove single-row CHECK"),
    (8, "06", "Ignore target upgrade gate"),
    (9, "07", "Ignore pending deployment configuration"),
    (10, "07", "Execute dotenv as shell"),
    (11, "08", "Run preflight after merge"),
    (12, "06", "Exit zero on automatic block"),
    (13, "09", "Lose previous commit in resume state"),
    (14, "09", "Repeat backup during resume"),
    (15, "09", "Remove resume loop guard"),
    (16, "10", "Probe MCP with GET"),
    (17, "10", "Treat HTTP 405 as healthy"),
    (18, "10", "Remove MCP probe timeout"),
    (19, "11", "Remove Starlette pin"),
    (20, "11", "Enable upgrade gate early"),
    (21, "11", "Change mcp_server.py baseline blob"),
    (22, "12", "Import transport protection in production"),
]

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--list", action="store_true")
    args = parser.parse_args()
    if not args.list:
        parser.exit(2, "NOT IMPLEMENTED: inventory only; no mutation evidence produced.\n")
    print(json.dumps([{"knife": f"K-PREP-{n}", "guard": f"T-PREP-01-{guard}",
                       "mutation": description, "status": "PLANNED"}
                      for n, guard, description in KNIVES], indent=2))
