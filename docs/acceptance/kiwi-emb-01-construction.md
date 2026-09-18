# EMB-01 construction evidence

2026-09-18. Constructor self-verification; independent review and deployment acceptance remain pending.

## Behavior

Embedding vectors now carry route profile, model, dimension and source-text hash. Searches exclude different identities and invalid vectors. Existing unversioned vectors become `unknown`; users explicitly confirm a potentially billable alignment. Missing-vector backfill remains available. Durable rebuild jobs use owner tokens, expiring leases, compare-and-swap writes and transactional counters. Provider response indices must form a complete permutation before identities are assigned.

The provider page places the embedding model selector beside alignment and diagnostics. Saving the model triggers one probe; manual testing is also available. Failures show bounded, redacted diagnostic fields, with expansion and copy. Failed/skipped rebuild counts remain visible. Save/edit generations and ordered writes prevent stale results and preserve the final selection when the user changes back while an earlier save is pending.

See [the mechanism](../embedding-versioning.md) and [upgrade instructions](../UPGRADING.md).

## Source and stages

- Base: `6936db7e8a09bbe25e4e1c37bb0cd9ba18416c3d` (`release/kiwi-sync`).
- Tests-only stage A: `5699bca`; two new files, no implementation or legacy fixture changes. Disposable Linux PostgreSQL 16: 16 Python groups, 19 named assertion failures, zero errors; initial Node suite: five failures, zero errors.
- B1: `9ed3611`; 13 applicable EMB Python groups passed. B2: `29571eb`; probe, UI, docs and full mutation suite. Subsequent commits added direct write-path/lease checks and fixed actual-page/save-order issues.
- Final implementation and checked-in ledger source: `277fbcd18ca36e30d4044ab2e2ab68b67d11e27c`.
- This delivery commit changes only documentation/evidence. All 44 distinct `source_blobs` entries from the six ledgers match its tree.
- PR: [#88](https://github.com/LucieEveille/kiwi-mem/pull/88), Draft, base `release/kiwi-sync`. No merge, deployment or version bump.

Stage checkpoints were constructor self-checks following the user's overall implementation authorization, not separate independent approvals. A standalone B1 subset ledger was not archived; the final full suite includes those mutations. Added subcases must not all be described as having existed in stage A.

## Final local validation

Independent Linux sandbox with disposable PostgreSQL 16, simulated model HTTP and the repository's pinned dependencies:

- 19 Python scripts and four Node scripts: every process exited zero.
- EMB: 16 Python groups, zero failures/errors; seven Node groups passed.
- SEC-01a 37; SEC-01b 12; THINK 12; PREP 13; BUILD 13; safety-sync PostgreSQL 184. Existing drawer, stream, calendar, MCP, cache and compression-reasoning regressions passed.
- Framework check: two fresh application lifespans, static admin, multipart upload and CORS passed.
- `compileall`, `git diff --check`, `pip check` passed. Test-created databases were removed.

| Ledger | Expected assertion RED | Documented equivalent |
|---|---:|---:|
| EMB-01 | 29 | 2 |
| THINK-01 | 10 | 0 |
| SEC-01b | 10 | 0 |
| BUILD-01 | 23 | 0 |
| PREP-01 | 29 | 0 |
| SEC-01a | 41 | 0 |
| Total | 142 | 2 |

All preflight and restored-suite exit codes are zero. EMB K-05e is contained by the Python filter, K-11e by the transactional owner check. CRASH is not RED. K-28 is exercised by the T-12 partial-None worker case rather than the specification's T-09 label. The historical SEC build-ledger filename is refreshed from the same SEC run, not counted as a seventh independent suite.

Actual isolated Chrome ran the real panel against local API fixtures: seven alignment states; probe success/failure/expand/copy; literal script-like diagnostic text; confirmation with current counts; model A/B save ordering under delayed responses; 404 hiding, 500 remaining visible, and polling stopping after navigation. This is UI evidence, not a real-provider or production end-to-end claim. The fixture omitted `/sync/projects`, producing an expected unrelated 404.

GitHub Actions for the implementation head: [run 35348530911](https://github.com/LucieEveille/kiwi-mem/actions/runs/35348530911). The current PR check identifies the delivery commit's own run; it also performs Docker build, dependency audit and all six mutation suites. Local WSL did not provide Docker or the optional busybox parser, so those optional local capabilities are not claimed.

## Clarifications and review boundaries

- Optional routes are checked before reading their profile, both before and after model calls. Changing A to B or removing the route discards the returned batch and ends under owner protection.
- Scaled normalization deliberately accepts finite `[1e308]`; zero, bool and non-finite vectors remain invalid. This resolves the specification's contradictory overflow expectation.
- The real digest insert exposed an inherited timestamp parameter type error; passing `datetime` to its `timestamptz` parameter fixes that tested persistence path.
- Existing assertions remain; route/result and scene identity fixtures were calibrated. The credential-guard AST scope explicitly includes the new controlled endpoints.
- Route checks do not promise a global atomic snapshot across every possible configuration edit. Results retain the identity of the request that produced them.
- Status scans eligible data in O(N); large-dataset performance was not benchmarked. Job/item retention has no dedicated purge policy yet.
- Diagnostic redaction covers known keys, URL encoding and specified patterns, not arbitrary encodings. Probe/rebuild calls can incur charges even if their later results are discarded.
- No real upstream embedding service, production database, pod fingerprint, backup or deployment was exercised. Independent CC review is pending. Keep the PR Draft until the release owner proceeds through the established gates.
