"""Core no-network regression checks for the permanent tool drawer."""

import asyncio
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import tool_drawer as td

RETURN_MESSAGE = "工具抽屉已是常驻模式：本会话展开的工具会一直保持可用，无需归还。"


def check(condition, message):
    if not condition:
        raise AssertionError(message)


async def main():
    td._sessions.clear()
    session = td._get_session("stability-core")
    session["expanded"] = ["memory"]
    session["rounds_no_use"] = 7

    td._append_expanded(session, "search")
    td._append_expanded(session, "memory")
    td._append_expanded_many(session, ["reminder", "search", "conversation"])
    check(
        session["expanded"] == ["memory", "search", "reminder", "conversation"],
        "expanded categories must append in first-seen order without duplicates",
    )

    expanded_before = list(session["expanded"])
    rounds_before = session["rounds_no_use"]
    result = await td.handle_meta_tool("_drawer_return_tools", {}, "stability-core")
    check(result == RETURN_MESSAGE, "legacy return must use the compatibility message")
    check(session["expanded"] == expanded_before, "legacy return must not shrink expanded")
    check(session["rounds_no_use"] == rounds_before, "legacy return must not change rounds_no_use")

    meta_names = {item["function"]["name"] for item in td._build_meta_tools()}
    check("_drawer_return_tools" not in meta_names, "legacy return must not be model-visible")

    with open(os.path.join(ROOT, "tool_drawer.py"), encoding="utf-8") as f:
        drawer_source = f.read()
    with open(os.path.join(ROOT, "config.py"), encoding="utf-8") as f:
        config_source = f.read()
    check("_AUTO_COLLAPSE_ROUNDS" not in drawer_source, "auto-collapse constant must be removed")
    check("drawer_auto_collapse_enabled" not in drawer_source, "drawer route must not read auto-collapse config")
    check("drawer_auto_collapse_enabled" not in config_source, "auto-collapse config must be removed")

    print("PASS: permanent drawer core stability")


if __name__ == "__main__":
    asyncio.run(main())

