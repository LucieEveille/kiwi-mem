# THINK-02 Stage B construction evidence

Status: implemented on PR #92 and rebased after LOCK-01 squash; Draft, pending independent replay of the integrated version. No merge or deployment is authorized by this report.

Current integration base: `b1dd5dfeec0f8f46da14306bce6b752cf2cbee06` (`release/kiwi-sync`, LOCK-01 #91 squash).
Integrated replay head: `42c2698a8bc25d06777ab445d846f3499eef18a9`.
Original contract base: `0cbd1afdf822e9a6c6aec8ebe4ffc4e64e27f2e9`.
Accepted tests-only Stage A: `38fbbfef0a9e412a1f599cd1d84daa6a8140649b`.
Historical implementation: `5b87acd79458c6d87edad8234fc8f359960e549f`; historical fixture calibration/replay: `5105ca4ba4ea9cfcc0ff9b3e8100026b4b8e3f1e`.
Pre-rebase delivery: `56a96469561f8189bdaa6c54f412a4de82001c51` (retained as a local backup branch).

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

THINK-01's twelve guards remain unchanged and pass; its ten mutations are RED. Disposable PostgreSQL 16.15 passes **198** permanent guards, including all seven LOCK guards (31 PASS / 0 FAIL / 0 ERROR sub-arms); W2-05b has 61 PASS / 0 FAIL / 0 ERROR sub-arms. W2-05b's 13 mutations are RED and its restored 198-guard full suite passes. These are disposable real-database tests; embedding, model and HTTP boundaries remain mocked. No real model/client session or production operation is claimed.

Affected PREP, BUILD, SEC-01a/01b, EMB, ERR, THINK-01, W2-05b and LOCK-01 books were replayed alongside THINK-02. The two historical SEC-01a filenames contain the same replay of their identical book; existing equivalent mutations retain their explicit status (EMB: 33 RED / 3 EQUIVALENT; ERR: 11 RED / 1 EQUIVALENT). LOCK's seven mutations are RED. The final evidence index records all eleven ledger files and verifies every pinned source blob against the integrated delivery tree; no CRASH or SURVIVED result remains.

Integrated CI: **PASS**, run [35728780538](https://github.com/LucieEveille/kiwi-mem/actions/runs/35728780538), pinned to the integrated replay head above. Both LOCK-01 and THINK-02 mutations are executed and uploaded by CI. The evidence-only follow-up does not alter the pinned source blobs; any automatically triggered follow-up CI is a separate run, not the source of these replay artifacts.

## Rebase reconciliation

The shared CHANGELOG, KNOWN_ISSUES and UPGRADING entries preserve both tickets. LOCK's accepted title and removal of its pending-acceptance sentence remain intact. CI retains the LOCK and THINK mutation steps and artifact paths, plus THINK's ten guard groups. The identical W2-05b fixture calibration already in the LOCK squash was automatically dropped from the rebased history.

`main.py`, the THINK-02 guard/knife files and the calibrated ERR guard are byte-identical to the pre-rebase delivery. LOCK's `database.py`, `dream.py`, `daily_digest.py`, safety guard file, LOCK knife and W2-05b knife are byte-identical to the integration base. Only shared documents/CI were reconciled; the boundary proof records these Git blob comparisons. [Integrated local checks](evidence/kiwi_think_02_rebase_checks.json).

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

Next gate: independent replay of this integrated THINK-02 delivery. PR #92 remains Draft; stop after delivery and await the user's next authorization.


## P1 — conservative object controls (construction complete; independent replay pending)

This section supersedes the original parsing/count claims above. The historical accepted Stage A counts were **147 FAIL / 112 PASS**, as recorded in its ledger. P1 follows instruction v1.2.2 and contract v1.6.2. Accepted P1 tests-only head: `a49808d`; implementation and replay head: `0c43b2621e034c40acb4a795366463e65bd4300c`. PR #92 remains Draft; no merge/deployment authorized.

Only two production sections change: `_parse_reasoning_object` and its entry branch. Classification distinguishes absent/null, valid and invalid controls. Valid false short-circuits effort validation; effort, nonnegative budget and true follow in order. Zero budget is a Kiwi off alias. With no usable valid control, invalid controls select off without panel fallback; empty/all-null/unknown-only objects fall back to panel. Diagnostics log field names only. Existing rejection shapes and outbound behavior are preserved. The four mechanism/upgrade/limitation/changelog sections describe the policy and upstream capability limit.

### Full green output and evidence

```text
Ran 10 tests
OK
THINK-02 SUMMARY {"ERROR": 0, "FAIL": 0, "PASS": 4955}
THINK-02 assertion_counts {"ERROR": 0, "FAIL": 0, "PASS": 9142}
ERR-01: 339 tests, OK
PASS: 198 total permanent behavior guards
K-THINK2-0 … K-THINK2-11: RED
```

All 4,868 accepted P1 Stage A subtest identities remain, now green. The additional 87 subtests are the three parser tuple fields for 29 cases, which could not execute against the old scalar return. Guard calibration keeps those field identities present even if a mutation breaks the tuple prerequisite; a business ValueError rejecting a valid input becomes a tuple-contract assertion failure, while unexpected exception types remain ERROR. An absent captured upstream body is asserted before inspecting its fields. No expected result was loosened. Assertion totals also include fixture checks and must not be confused with subtest totals.

The dynamic knife preflight records 4,955 unique identities, compares the full guard/arm-parameter set for every mutation and restoration, and requires named target AssertionErrors with zero ERROR arms. K-2/K-5 anchors match the new code exactly once; K-8…11 cover conservative fallback, empty-object fallback, valid-control priority and zero budget. All twelve are RED and restored green.

| Evidence | Stage A | Stage B |
|---|---|---|
| Per-arm table | [A arms](evidence/kiwi_think_02_p1_stage_a_arms.tsv) | [B arms](evidence/kiwi_think_02_p1_stage_b_arms.tsv) |
| Per-assertion table | [A assertions](evidence/kiwi_think_02_p1_stage_a_assertions.tsv) | [B assertions](evidence/kiwi_think_02_p1_stage_b_assertions.tsv) |

[Twelve-knife ledger](evidence/kiwi_think_02_knives.json), [all eleven ledger fingerprints](evidence/kiwi_think_02_p1_evidence_index.json), [checks](evidence/kiwi_think_02_p1_checks.json), [frozen slice proof](evidence/kiwi_think_02_p1_boundaries.json). Ten inherited ledger files plus this ticket make eleven; the two SEC-01a names contain the same book replay. Existing EMB/ERR equivalent mutations retain their EQUIVALENT classification, never relabeled RED.

CI [run 35877901656](https://github.com/LucieEveille/kiwi-mem/actions/runs/35877901656) passes at the implementation head. W2-05b's thirteen knives and full 198-guard preflight/restoration were additionally replayed on local disposable PostgreSQL 16. Models, embeddings and HTTP boundaries are mocked; this is not a real-client/provider or production claim. The local test database was removed and the cluster stopped. Evidence-only follow-up preserves every pinned source blob.

Frozen SHA256 values, before (`60fc44c`) and after, are identical:

| Slice | Before = after |
|---|---|
| `_apply_reasoning` | `429e1e5e41ad269d9ec6d0fac13e6f9edc05dba694c91d073e48705b99af81e7` |
| `_EFFORT_BUDGET` | `56e4593182cdf8b7a1439808632ec6afac945ea13f609f7c6330892f0de0bc1f` |

Next gate: independent parser and final-outbound matrix replay, including three panel values, four endpoint profiles, and ordinary forwarding/tool-loop dispatch. Stop after this delivery.
