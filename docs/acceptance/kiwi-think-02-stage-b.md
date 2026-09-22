# THINK-02 Stage B construction evidence

Status: implemented on PR #92; Draft, pending independent replay and a later rebase after LOCK-01 merges. No merge or deployment is authorized by this report.

Base: `0cbd1afdf822e9a6c6aec8ebe4ffc4e64e27f2e9` (`release/kiwi-sync`).
Accepted tests-only Stage A: `38fbbfef0a9e412a1f599cd1d84daa6a8140649b`.
Implementation: `5b87acd79458c6d87edad8234fc8f359960e549f`.
Fixture calibration and replay head: `5105ca4ba4ea9cfcc0ff9b3e8100026b4b8e3f1e`.

## Result and limits

Input parsing accepts `none → off` and `minimal → low`, and OpenRouter-style reasoning objects. Non-null explicit strings are validated first and win over objects. Otherwise an object resolves enabled=false, effort/aliases, then positive-integer budget floors; absent/null inputs retain panel/default precedence. Malformed explicit input keeps the nested four-key 400 shape without echoing values. Object errors name `reasoning`.

Output translation, endpoint ceilings, the adapter budget table and the seven public enum values are unchanged. Minimal-to-low and budgets below 5000 are lossy mappings. Off omits gateway reasoning controls; it cannot guarantee that a model stops reasoning. Exclude/include_reasoning retain their existing path-specific handling.

## Guards and mutations

All **259 sub-arms in ten groups PASS**, with the same arm identities as accepted Stage A (147 PASS / 112 assertion FAIL / 0 ERROR). Guards call real ASGI/adapter functions with fake configuration, storage and upstream transport. No real model/client session is claimed.

| Guard suffix | Passing sub-arms |
|---|---:|
| 00 aliases | 34 |
| 01 object entry | 11 |
| 02 outbound | 129 |
| 03 panel conflict | 8 |
| 04 budget | 14 |
| 05 auto | 9 |
| 06 precedence | 26 |
| 07 rejection | 8 |
| 08 logs | 16 |
| 09 regression | 4 |

K-THINK2-0 through K-THINK2-7 are all **RED from their named target assertions, zero ERROR arms**; 259-arm checks pass before and after byte-for-byte restoration. [Knife ledger](evidence/kiwi_think_02_knives.json), [per-arm transition table](evidence/kiwi_think_02_stage_b_guards.json).

THINK-01's twelve guards remain unchanged and pass; its ten mutations remain RED. The complete ERR suite passes 339 tests, including one new six-case self-test of the narrow input-validator exception allowance. ERR mutations retain 11 RED / 1 pre-existing EQUIVALENT. Disposable PostgreSQL 16 passes **191** inherited permanent guards on this independent branch; LOCK's seven guards will join only after the required later rebase. W2-05b's 13 mutations and restored full suite pass.

Affected PREP, BUILD, SEC-01a/01b, EMB, ERR, THINK-01 and W2-05b books are replayed in `evidence/`. The two historical SEC-01a filenames contain the same replay of their identical book; existing equivalent mutations retain their explicit status.

Complete CI: **PASS**. Run [35723090192](https://github.com/LucieEveille/kiwi-mem/actions/runs/35723090192), pinned to the replay head above. THINK-02 mutations are now executed and uploaded by CI. Evidence-only follow-up commits do not alter the pinned source blobs.

## Calibrations and zero-diff proof

1. Two new T-02 outbound sub-arms had expected one downgrade log in a tool loop. Direct replay on `0cbd1af` with the existing THINK-01 request harness shows two for xhigh/max (one at entry, one in the loop); ordinary forwarding shows one. Only those new test expectations were corrected. `_apply_reasoning` was not changed to satisfy the mistaken expectation.
2. ERR's source locator now selects the first ValueError handler for string X1, as THINK-02 adds a second handler for objects. Its static exception detector recognizes `_reasoning_400` only for the matching literal parameter around the corresponding input validator in `chat_completions`. Six self-test cases confirm that unrelated functions, work, exception types and parameter values remain rejected.
3. W2-05b fixture creation times are fixed and distinct to remove coarse-clock ordering ties, also reproduced on the original base. Assertions and application ordering remain unchanged. Existing knife anchors are calibrated to the new resolver call; W2-05b's runner handles the precise inherited/LOCK suite size.

The base and head source-slice SHA256 values are identical:

| Slice | SHA256 |
|---|---|
| `_apply_reasoning` | `429e1e5e41ad269d9ec6d0fac13e6f9edc05dba694c91d073e48705b99af81e7` |
| adapter `_EFFORT_BUDGET` | `56e4593182cdf8b7a1439808632ec6afac945ea13f609f7c6330892f0de0bc1f` |

[Full boundary proof](evidence/kiwi_think_02_boundaries.json) also covers endpoint helpers and unchanged config, adapter, panel schema and THINK-01 guard files. Public reasoning docs include the six-client pinned source table, mapping rules and remaining limitations.

Next gate: LOCK-01 independent acceptance and separately authorized squash; then rebase this branch, reconcile shared docs/CI and regenerate affected evidence against the integrated head before final THINK-02 acceptance.
