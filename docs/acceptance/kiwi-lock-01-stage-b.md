# LOCK-01 Stage B construction evidence

Status: implemented on PR #91; Draft, pending independent replay. No merge or deployment is authorized by this report.

Base: `0cbd1afdf822e9a6c6aec8ebe4ffc4e64e27f2e9` (`release/kiwi-sync`).
Accepted tests-only Stage A: `b714c8aedc17943f9d36694b28244593a5956a89`.
Implementation: `2e724318cb9a97ee0774ef5a3637bff54b3e9de9`.
Fixture calibration and replay head: `788bfd1c6b741729434538243802a0be0f20d57b`.

## Result and limits

Dream promotion now updates only global rows whose lock source is distinct from `user`, and returns whether PostgreSQL actually updated a row. A rejected action records `success=false`, `reason=user_locked_or_out_of_scope`, and the fixed skip event. Promotion statistics and infrastructure-error handling retain their existing behavior.

Retirement retains the existing SELECT and age predicate. Its UPDATE rechecks permanent state and auto/dream source atomically, and derives count, titles and logging from returned IDs. It does not migrate historical rows or recheck the access-time cutoff after selection.

## Guards and mutations

Local PostgreSQL 16.15: **198 permanent guards PASS** (191 inherited + seven LOCK groups). The same 31 new sub-arm identities accepted in Stage A now all pass, versus 14 PASS / 17 assertion FAIL / 0 ERROR in Stage A.

| Guard | Passing sub-arms |
|---|---:|
| T-LOCK-01-01 | 4 |
| T-LOCK-01-02 | 4 |
| T-LOCK-01-03 | 2 |
| T-LOCK-01-04 | 2 |
| T-LOCK-01-05 | 12 |
| T-LOCK-01-06 | 2 |
| T-LOCK-01-07 | 5 |

The six original LOCK scenarios call the real database. T-07 simulates the stale SELECT return boundary while passing UPDATE/RETURNING to real PostgreSQL; it is not a two-connection concurrent-scheduling test. The full inherited suite uses its existing embedding/model/HTTP fakes. All databases are disposable loopback databases; no production/model validation is claimed.

K-LOCK-1 through K-LOCK-7 are all **RED from their named target assertions, zero ERROR arms**. Full 198-guard checks pass before mutation and after byte-for-byte restoration. Both states and assertion reasons are in the [knife ledger](evidence/kiwi_lock_01_knives.json). [Per-arm transition table](evidence/kiwi_lock_01_stage_b_guards.json).

The affected PREP, BUILD, SEC-01a, EMB, ERR, THINK-01 and W2-05b books are replayed in `evidence/`. Both historical SEC-01a ledger filenames receive the same replay of their identical book. W2-05b has 13 RED mutations and full-suite restoration. Existing explicitly equivalent EMB/ERR mutations retain EQUIVALENT status rather than being relabeled RED.

Complete CI: **PASS**. Run [35723084216](https://github.com/LucieEveille/kiwi-mem/actions/runs/35723084216), pinned to the replay head above. New LOCK mutation execution and evidence upload are wired into CI. Evidence-only follow-up commits do not alter the pinned source blobs.

## Test calibration and frozen boundaries

The inherited W2-05b fixture used successive wall-clock timestamps and compared whole ordered responses across independent resets. On Windows, identical timestamps produced ties and intermittent G3/G4 ordering changes. This also reproduced on unmodified `0cbd1af` (60 PASS / 1 assertion FAIL / 0 ERROR). The fixture now assigns distinct fixed timestamps. All existing assertions, group identities, query logic and application ordering remain unchanged. The W2-05b runner accepts the exact suite size appropriate to the branch (191, or 198 when LOCK groups are present).

The retirement SELECT literal, `_check_auto_lock`, `get_unprocessed_memories`, `get_permanent_memories`, `set_memory_permanent_scoped`, batch-update handler and W2-05b guard body match the base. [Git-object source-slice hashes](evidence/kiwi_lock_01_boundaries.json).

The required issue entry, event-ledger statement, changelog and upgrading notes are updated. The separate Chat consumer was source-inspected: action payloads are forwarded without a fixed-key schema; the memory page does not register an action callback. This is source compatibility evidence, not UI end-to-end acceptance.

Next gate: independent replay and narrow review. LOCK must be accepted and separately authorized for squash before THINK-02 rebases and receives its final integrated acceptance.
