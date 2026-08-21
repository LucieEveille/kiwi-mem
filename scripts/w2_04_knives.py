#!/usr/bin/env python3
"""W2-04 变异刀本：可复现、可复核、不碰你的工作区。

每把刀 = 对一个生产文件做一处精确替换，跑完整守卫套件，断言它**红在指定守卫的指定
断言文本上**，然后恢复。非零退出本身不算 RED——那可能只是撞上了一个语法错误或崩溃；
只有"目标守卫 + 目标文本"都对上才记 RED。

安全边界（爹爹返工卡 v3.1 §B3）：
  · ROOT / DSN / 结果路径全走环境变量；
  · 施刀在一次性 git worktree 里做，**绝不**在你的工作区执行 `git checkout --`；
  · 开刀前校验工作区干净、head 等于申报 SHA、baseline 全绿；
  · 每刀后校验被改文件的 sha256 已恢复原样。

用法：
    KIWI_KNIFE_DSN=postgresql://... python scripts/w2_04_knives.py            # 全跑
    KIWI_KNIFE_DSN=postgresql://... python scripts/w2_04_knives.py A1 R2-user # 挑着跑

环境变量：
    KIWI_KNIFE_REPO     仓库路径（默认：本脚本所在仓库）
    KIWI_KNIFE_DSN      一次性 PostgreSQL 的管理 DSN（必填）
    KIWI_KNIFE_OUT      结果 JSON 落点（默认 <repo>/.knife-results.json）
    KIWI_KNIFE_SHA      期望的 head SHA（填了就校验，防止对错版本施刀）
    KIWI_KNIFE_TIMEOUT  单次套件超时秒数（默认 1500）
"""
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

REPO = os.path.abspath(os.environ.get("KIWI_KNIFE_REPO") or
                       os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DSN = os.environ.get("KIWI_KNIFE_DSN", "")
OUT = os.environ.get("KIWI_KNIFE_OUT") or os.path.join(REPO, ".knife-results.json")
EXPECT_SHA = os.environ.get("KIWI_KNIFE_SHA", "")
TIMEOUT = int(os.environ.get("KIWI_KNIFE_TIMEOUT", "1500"))
SUITE = os.path.join("scripts", "test_kiwi_safety_sync.py")

# (tag, 说明, 目标文件, 目标守卫标识, 可接受红点文本（str 或 tuple，任一命中即可）,
#  原文, 替换, 额外静默 tag)
#
# 期望文本写成元组时，同一守卫里的任意一句断言命中都算数：守卫补一句更强的断言不该
# 让刀账变成 RED-ELSEWHERE。真正要防的是"红在别的守卫上"，那由目标守卫编号把关。
KNIVES = [
    ("R1", "带键单删不扫无键 legacy 行", "database.py", "T-W2-04-35",
     "key-less legacy rows survived a keyed delete",
     '''                swept_legacy = await _sweep_unlinked_legacy_rows_tx(conn, conv_id)
                if swept_legacy:
                    ledger_deleted += swept_legacy
                    ledger_mode = "turn+legacy_sweep"''',
     '''                swept_legacy = 0''', ()),

    ("R2-notpresent", "not-present 删除只盖章、不清副本", "database.py", "T-W2-04-36",
     "must still clear the compression summaries",
     '''                ledger_mode = "not_present"
                role, turn_key = None, None
                deleted = False''',
     '''                ledger_mode = "not_applicable"
                role, turn_key = None, None
                deleted = False
                return {"deleted": False, "ledger_events_deleted": 0,
                        "ledger_mode": "not_present",
                        "purged": {"compression_summaries": 0, "compression_dividers": 0,
                                   "handoff_dividers": 0},
                        "source_rev": await _bump_source_rev_tx(conn, conv_id)}''', ()),

    ("R2-user", "落账不查 user 的消息章", "database.py", "T-W2-04-36",
     "the stamped user message still reached the ledger",
     '''                user_blocked = bool(user_message_id) and await _message_tombstoned_tx(
                    conn, session_id, user_message_id)''',
     '''                user_blocked = False''', ()),

    ("R2-assistant", "落账不查 assistant 的消息章", "database.py", "T-W2-04-36",
     "the stamped assistant message still reached the ledger",
     '''                assistant_blocked = bool(assistant_message_id) and await _message_tombstoned_tx(
                    conn, session_id, assistant_message_id)''',
     '''                assistant_blocked = False''', ()),

    ("R2-legacy", "闸门关的落账不查消息章", "database.py", "T-W2-04-36",
     "the closed-gate path ignored the",
     '''            user_blocked = bool(user_message_id) and await _message_tombstoned_tx(
                conn, session_id, user_message_id)
            assistant_blocked = bool(assistant_message_id) and await _message_tombstoned_tx(
                conn, session_id, assistant_message_id)''',
     '''            user_blocked = False
            assistant_blocked = False''', ()),

    ("R2-noline", "落账不记 source_message_id", "database.py", "T-W2-04-36",
     "both ledger rows must record which message they came from",
     '''                    "VALUES ($1, 'user', $2, $3, $4, $5, $6, $7) RETURNING id",
                        session_id, user_content, model, project_id, scope_known, turn_key,
                        user_message_id,''',
     '''                    "VALUES ($1, 'user', $2, $3, $4, $5, $6, $7) RETURNING id",
                        session_id, user_content, model, project_id, scope_known, turn_key,
                        None,''', ()),

    ("R2-belt", "not-present 不清候选轮次键那一轮", "database.py", "T-W2-04-36",
     ("a turn_key-only client's deleted sentence is still sitting in the ledger",
      "must be stamped, or it just lands again",
      "the belt must still close the turn it guessed at",
      "must be what the belt aims at"),
     '''                if declared_role != "assistant":
                    belt_key = declared_turn_key or msg_id
                    by_key = await conn.execute(
                        "DELETE FROM conversations WHERE session_id = $1 AND turn_key = $2",
                        conv_id, belt_key,
                    )
                    ledger_deleted += _rowcount(by_key)''',
     '''                if declared_role != "assistant":
                    belt_key = declared_turn_key or msg_id
                    by_key = "DELETE 0"''', ()),

    ("A1-uncond", "命中①就不再无条件清扫", "database.py", "T-W2-04-36",
     "a precise hit cancelled the sweep",
     '''                ledger_deleted += await _sweep_unlinked_legacy_rows_tx(conn, conv_id)''',
     '''                if ledger_deleted == 0:
                    ledger_deleted += await _sweep_unlinked_legacy_rows_tx(conn, conv_id)''', ()),

    ("A1-keyed", "清扫放过带 turn_key 的无关联行", "database.py", "T-W2-04-35",
     "a keyed row that cannot name its message survived",
     '''        DELETE FROM conversations
        WHERE session_id = $1 AND source_message_id IS NULL''',
     '''        DELETE FROM conversations
        WHERE session_id = $1 AND turn_key IS NULL AND source_message_id IS NULL''', ()),

    ("belt-role", "not-present 不理会客户端声明的 role", "database.py", "T-W2-04-36",
     "still closed the turn behind the belt",
     '''                if declared_role != "assistant":''',
     '''                if True:''', ()),

    ("A2-entry", "聊天入口把两条消息 ID 丢掉", "main.py", "T-W2-04-40",
     "must carry both message ids all the way to the ledger",
     '''        "user_message_id": user_message_id,
        "assistant_message_id": assistant_message_id,''',
     '''        "user_message_id": None,
        "assistant_message_id": None,''', ()),

    ("A2-halfpair", "聊天入口放行半对消息 ID", "main.py", "T-W2-04-40",
     "must be refused, got",
     '''    if (user_id_present or assistant_id_present) and (
            user_message_id is None or assistant_message_id is None):''',
     '''    if False and (user_id_present or assistant_id_present) and (
            user_message_id is None or assistant_message_id is None):''', ()),

    ("A2-passthrough", "聊天入口不摘 ID、原样透传上游", "main.py", "T-W2-04-40",
     "was passed through to the provider",
     '''            if key in body:
                value = body.pop(key)''',
     '''            if key in body:
                value = body.get(key)''', ()),

    ("R3a", "换窗压缩后不做终检", "main.py", "T-W2-04-37",
     "the prompt builder injected a handoff whose source was deleted mid-flight",
     '''                    still_there = await handoff_source_unchanged(
                        data["source_session_id"], data["source_rev"])''',
     '''                    still_there = True''', ()),

    ("R3a-rev", "换窗快照不带来源版本", "database.py", "T-W2-04-37",
     "handoff data must carry the version it was read at",
     '''        "source_session_id": source_conversation_id,
        "source_rev": source_rev,''',
     '''        "source_session_id": source_conversation_id,''', ()),

    ("R3b-single", "单 PUT 不验换窗来源", "database.py", "T-W2-04-37",
     "a handoff divider from a deleted source must be refused",
     '''            if _handoff is not None:
                # 换窗卡看的是**来源**会话的存活与版本。
                if not await _handoff_source_alive_tx(conn, _handoff[0], _handoff[1]):
                    return ("对话素材已变化", 409, "sources_changed")''',
     '''            if False:
                pass''', ()),

    ("R3b-batch", "全量替换/import 不验换窗来源", "database.py", "T-W2-04-37",
     "the late handoff divider came back through a full replace",
     '''        handoff = _handoff_divider_source(message)
        if handoff is not None:
            source_id, source_rev = handoff
            if not await _handoff_source_alive_tx(conn, source_id, source_rev):
                skipped["sources_changed"].append(mid)
                continue''',
     '''        handoff = None''', ()),

    ("R3c", "删源不清跨会话换窗卡", "database.py", "T-W2-04-38",
     "left its handoff copy alive in another conversation",
     '''    rows = await conn.fetch(
        "SELECT id, conversation_id FROM chat_messages "
        "WHERE role = 'divider' AND handoff_info->>'sourceId' = $1",
        source_id,
    )
    if not rows:
        return 0''',
     '''    rows = []
    if not rows:
        return 0''', ()),

    ("R3c-rev", "清跨会话副本不 bump 目标 rev", "database.py", "T-W2-04-38",
     "target conversation's rev must move",
     '''    for target in sorted({r["conversation_id"] for r in rows}):
        await _bump_source_rev_tx(conn, target)
    return len(rows)


async def _handoff_source_alive_tx''',
     '''    return len(rows)


async def _handoff_source_alive_tx''', ()),

    ("R3c-lockorder", "跨会话取锁不排序", "database.py", "T-W2-04-38",
     ("session locks must be taken in ascending id order",
      "must impose a canonical order"),
     '''    for session_id in sorted({s for s in session_ids if s}):
        await _lock_session(conn, session_id)''',
     '''    for session_id in {s for s in session_ids if s}:
        await _lock_session(conn, session_id)''', ()),

    ("R3-legacy", "历史无来源换窗卡不清理", "database.py", "T-W2-04-38",
     "must be cleaned by the migration",
     '''        await _cleanup_sourceless_handoff_dividers(conn)''',
     '''        pass''', ()),

    ("R4", "备份恢复无条件撤章", "database.py", "T-W2-04-39",
     "must lift no message stamp",
     '''    if messages:
        named_ids = [str(m.get("id")) for m in messages if m.get("id")]''',
     '''    if True:
        await conn.execute("DELETE FROM message_tombstones WHERE session_id = $1", session_id)
        await conn.execute("DELETE FROM turn_tombstones WHERE session_id = $1", session_id)
    if messages:
        named_ids = [str(m.get("id")) for m in messages if m.get("id")]''', ()),

    ("R5", "单 PUT 的来源版本不排除 bool", "database.py", "T-W2-04-20",
     "a boolean source rev must be refused",
     '''                if (not isinstance(expected, int) or isinstance(expected, bool)
                        or expected != current):
                    return ("对话素材已变化", 409, "sources_changed")''',
     '''                if not isinstance(expected, int) or expected != current:
                    return ("对话素材已变化", 409, "sources_changed")''', ()),

    ("R6", "爹爹刀 κ：只清第一条自动 divider", "database.py", "T-W2-04-24",
     "every auto divider must be counted, not just the first",
     '''            if doomed_dividers:''',
     '''            doomed_dividers = doomed_dividers[:1]
            if doomed_dividers:''', ("T-W2-04-7-purge-receipt", "T-W2-04-7-divider-count")),

    ("epsilon", "爹爹刀 ε：import/全量替换不滤已盖章 ID", "database.py", "T-W2-04-30",
     "import re-seeded a stamped message id",
     '''        if mid and mid in stamped_ids:
            skipped["message_deleted"].append(mid)
            continue
''',
     '''''',
     # 这一条被三层更早的同通道守卫先咬住，静默它们才能看见 T-30 自己咬。
     ("T-W2-04-10-replace-names", "T-W2-04-10-replace-state",
      "T-W2-04-24-replace", "T-W2-04-24-import")),

    ("C-delete-stamps", "整删不盖可见消息与轮次章", "database.py", "T-C-01",
     "conversation delete failed to stamp visible message id",
     '''            await _stamp_visible_messages_tx(conn, conv_id)
            await _stamp_session_tx(conn, conv_id)''',
     '''            await _stamp_session_tx(conn, conv_id)''', ()),

    ("C-reset-stamps", "reset 不盖可见消息与轮次章", "database.py", "T-C-04",
     "reset + metadata restore reopened a ledger-only identity",
     '''            for session_id in session_ids:
                await _stamp_visible_messages_tx(conn, session_id)
                await _stamp_session_tx(conn, session_id)''',
     '''            for session_id in session_ids:
                await _stamp_session_tx(conn, session_id)''', ()),

    ("C-restore-metadata", "metadata-only 恢复无条件撤消息与轮次章", "database.py", "T-W2-04-39",
     "a metadata-only backup speaks for no message and must lift no message stamp",
     '''    await conn.execute("DELETE FROM session_tombstones WHERE session_id = $1", session_id)
    if messages:''',
     '''    await conn.execute("DELETE FROM session_tombstones WHERE session_id = $1", session_id)
    await conn.execute("DELETE FROM message_tombstones WHERE session_id = $1", session_id)
    await conn.execute("DELETE FROM turn_tombstones WHERE session_id = $1", session_id)
    if messages:''', ()),

    ("C-restore-unnamed", "非空恢复撤掉未点名消息章", "database.py", "T-W2-04-39",
     "a backup that never mentions a message must leave its stamp in place",
     '''                "DELETE FROM message_tombstones WHERE session_id = $1 AND message_id = ANY($2::text[])",
                session_id, named_ids,''',
     '''                "DELETE FROM message_tombstones WHERE session_id = $1",
                session_id,''', ()),

    ("C-restore-handoff", "备份恢复不滤无来源换窗卡", "database.py", "T-C-05",
     "restore did not report all seven filtered handoffs",
     '''    if messages is not None:
        messages, filtered_count = _drop_sourceless_handoffs(messages)''',
     '''    if messages is not None:
        filtered_count = 0''', ()),

    ("C-filter-outside-tx", "无来源换窗卡过滤挪到恢复事务外", "database.py", "T-C-05",
     "restore did not report all seven filtered handoffs",
     '''    """备份恢复的公开入口：一段对话一个事务，原子完成撤章与重建。"""
    pool = await get_pool()''',
     '''    """备份恢复的公开入口：一段对话一个事务，原子完成撤章与重建。"""
    if messages is not None:
        messages, _ = _drop_sourceless_handoffs(messages)
    pool = await get_pool()''', ()),

    ("C-capability-schema", "能力端点忽略 schema readiness", "main.py", "T-C-07",
     "missing ticket-C schema did not fail closed with a fixed contract",
     '''            w2_04_initialized()
            and await probe_w2_04_schema()
            and await get_config_bool(''',
     '''            w2_04_initialized()
            and True
            and await get_config_bool(''', ()),

    ("C-list-revision", "对话列表漏掉 source_rev 联表", "database.py", "T-C-08",
     "a never-bumped conversation did not list integer source_rev=0",
     '''                   c.pinned, c.sort_order, c.created_at, c.updated_at,
                   COALESCE(r.rev, 0) AS source_rev
            FROM chat_conversations c
            LEFT JOIN session_source_rev r ON r.session_id = c.id''',
     '''                   c.pinned, c.sort_order, c.created_at, c.updated_at
            FROM chat_conversations c''', ()),

    ("C-search-final", "搜索省略删除与版本终检", "database.py", "T-C-09",
     "the search final-check seam was never reached",
     '''        return await _search_final_check(conn, results, initial_state)''',
     '''        return results''', ()),

    ("C-reminder-source", "消息序列化漏写 reminder_source_id", "database.py", "T-C-12",
     "detail lost reminder_source_id for tc12-single",
     '''        (msg.get("reminderSourceId") if isinstance(msg.get("reminderSourceId"), str)
         else msg.get("reminder_source_id")
         if isinstance(msg.get("reminder_source_id"), str) else None),''',
     '''        None,''', ()),

    ("C-gate-gates-stamps", "能力开关误作删除盖章总闸", "database.py", "T-C-07",
     "gate off stopped delete stamping visible message ids",
     '''    messages = await conn.execute("""
        INSERT INTO message_tombstones (session_id, message_id)''',
     '''    from config import get_config_bool
    if not await get_config_bool(
            "sync_delete_privacy_capability_enabled", fallback=True):
        return {"messages": 0, "turns": 0}
    messages = await conn.execute("""
        INSERT INTO message_tombstones (session_id, message_id)''', ()),

    ("C-handoff-select-star", "换窗取材 SELECT * 透传提醒来源", "database.py", "T-C-12",
     "handoff upstream row exposed reminder source keys",
     '''        SELECT role, content, summary, sort_order, time
        FROM chat_messages''',
     '''        SELECT *
        FROM chat_messages''', ()),
]


def sh(*args, cwd=None, check=True):
    return subprocess.run(args, cwd=cwd or REPO, capture_output=True, text=True, check=check)


def sha256(path):
    return hashlib.sha256(open(path, "rb").read()).hexdigest()


def run_suite(cwd, mute=()):
    env = {**os.environ, "KIWI_TEST_DATABASE_URL": DSN}
    if mute:
        env["KIWI_KNIFE_MUTE"] = ",".join(mute)
    else:
        env.pop("KIWI_KNIFE_MUTE", None)
    proc = subprocess.run([sys.executable, SUITE], cwd=cwd, capture_output=True,
                          text=True, timeout=TIMEOUT, env=env)
    return proc.returncode, proc.stdout + proc.stderr


def preflight():
    if not DSN:
        sys.exit("KIWI_KNIFE_DSN is required (a disposable PostgreSQL admin DSN)")
    dirty = sh("git", "status", "--porcelain").stdout.strip()
    if dirty:
        sys.exit(f"refusing to run: working tree is not clean\n{dirty}")
    head = sh("git", "rev-parse", "HEAD").stdout.strip()
    if EXPECT_SHA and not head.startswith(EXPECT_SHA):
        sys.exit(f"refusing to run: head {head[:12]} != declared {EXPECT_SHA}")
    print(f"head {head[:12]}, working tree clean")
    print("baseline: running the full suite unmutated…", flush=True)
    code, out = run_suite(REPO)
    total = re.search(r"PASS: (\d+) total permanent behavior guards", out)
    if code != 0 or not total:
        sys.exit(f"refusing to run: baseline is not green\n{out[-2000:]}")
    print(f"baseline green: {total.group(1)} guards\n")
    return head, int(total.group(1))


def main():
    head, baseline = preflight()
    only = set(sys.argv[1:])
    work = tempfile.mkdtemp(prefix="kiwi-knives-")
    tree = os.path.join(work, "tree")
    sh("git", "worktree", "add", "--detach", tree, head)
    results = []
    try:
        for tag, name, filename, target, expect_text, old, new, mute in KNIVES:
            if only and tag not in only:
                continue
            path = os.path.join(tree, filename)
            src = open(path, encoding="utf-8").read()
            before = sha256(path)
            if old not in src:
                results.append({"knife": tag, "name": name, "verdict": "PATCH-MISS",
                                "detail": "anchor not found"})
                print(f"{tag}: PATCH-MISS (anchor not found)", flush=True)
                continue
            open(path, "w", encoding="utf-8").write(src.replace(old, new, 1))
            try:
                code, out = run_suite(tree, mute)
                detail, verdict = _verdict(code, out, target, expect_text)
            except subprocess.TimeoutExpired:
                code, verdict, detail = -1, "TIMEOUT", f"suite exceeded {TIMEOUT}s (deadlock?)"
            finally:
                open(path, "w", encoding="utf-8").write(src)
            assert sha256(path) == before, f"{filename} was not restored after knife {tag}"
            results.append({"knife": tag, "name": name, "file": filename, "target": target,
                            "muted": list(mute), "verdict": verdict, "detail": detail})
            print(f"{tag} ({name}) -> {verdict}: {detail}", flush=True)
    finally:
        sh("git", "worktree", "remove", "--force", tree, check=False)
        shutil.rmtree(work, ignore_errors=True)
    payload = {"head": head, "baseline_guards": baseline, "knives": results}
    open(OUT, "w", encoding="utf-8").write(json.dumps(payload, ensure_ascii=False, indent=2))
    print(f"\nwrote {OUT}")
    bad = [r for r in results if r["verdict"] != "RED"]
    return 1 if bad else 0


def _verdict(code, out, target, expect_text):
    """非零退出还不够：必须**红在目标守卫里**、且断言文本对得上，才算这把刀被咬住。

    红在哪一条守卫，以断言前打出的最后一个 `BEGIN T-xx` 为准（套件每条守卫开跑前打
    一行）。以前这里拿 traceback 的函数名做模糊匹配，一条刀红在隔壁守卫上照样能算数；
    现在守卫编号真参与裁决，对不上就是 RED-ELSEWHERE，并把实际咬住它的守卫写进刀账。
    """
    if code == 0:
        return "suite still fully green", "SURVIVED"
    assertion = re.search(r"AssertionError: (.*)", out)
    begins = re.findall(r"^BEGIN (\S+)", out, flags=re.MULTILINE)
    reached = begins[-1] if begins else "(no guard started)"
    if not assertion:
        tail = out.strip().splitlines()[-1][:160]
        return f"non-assertion failure in {reached}: {tail}", "CRASH"
    text = assertion.group(1)[:200]
    if reached != target:
        return f"red in {reached}, not in {target}: {text}", "RED-ELSEWHERE"
    wanted = (expect_text,) if isinstance(expect_text, str) else tuple(expect_text or ())
    if wanted and not any(w and w in text for w in wanted):
        return f"red in {target}, but on another assertion: {text}", "RED-ELSEWHERE"
    return f"[{reached}] {text}", "RED"


if __name__ == "__main__":
    raise SystemExit(main())
