# EMB-01-P patch evidence

2026-09-18. Constructor self-verification; this does not substitute for independent CC review or release acceptance.

## Problem and behavior

The PR's constructor adversarial review found three reproducible gaps at `6c3a6ee611cbef05a93863c15217d85a7d6466d9`: lower-case percent escapes bypassed diagnostic key matching, upstream HTTP reason phrases reached httpx INFO logs before diagnostic redaction, and transaction-start lease time could accept an owner after a row-lock wait crossed expiry.

- Diagnostic comparisons now inspect the original, percent-hex-normalized and once-URL-decoded strings. Credential case remains significant. Matching fields are hidden before truncation; safe text is not replaced by a comparison copy.
- A narrow, idempotent filter on both httpx and httpcore replaces only the reason argument in the known five-argument HTTP Request summary. Method, URL, protocol, status, unrelated records and logger levels remain intact.
- Owner validation acquires the job row lock, then checks live expiration in a separate statement. Claim, renewal and final-state expiry conditions use `clock_timestamp()`. An owner expired while waiting cannot renew or write progress/final state. Existing owner-replacement guards remain.

See [the bilingual mechanism](../embedding-versioning.md). No schema, product choice, UI behavior, release version or deployment changes are part of this patch.

## Commits and local evidence

- P-A tests-only: `2fcf44fc93ee79b7bfdf14f81ffc0f6d513522d8`. Three added regression groups on the unchanged implementation: **12 assertion failures, zero errors**. Six encoded-field subcases, actual TCP plus two logger-signature subcases, and three lease-expiry actions fail independently.
- P-B implementation: `9c054a3217ff71c6dfa8988187d72beff5f7bc97`. Same patch groups green; complete EMB **19 Python groups**, zero failures/errors, plus seven Node groups.
- Evidence follows in a separate documentation-only commit so ledger `head` values identify an already committed, tested implementation. This adds one evidence commit to the task's two construction commits; no test history is rewritten.
- All **19 Python scripts and four Node scripts** in the CI behavior list exited zero in isolated Linux/PostgreSQL 16. SEC-01a 37, safety-sync 184, PREP 13, BUILD 13, SEC-01b 12 and THINK 12 pass. Framework compatibility, drawer/stream/calendar/MCP/cache/compression regressions also pass.
- `compileall`, `pip check` and full-branch `git diff --check` pass. Actual upstream model services and production are not contacted. The added HTTP check uses a real ephemeral loopback TCP server; the probe's ASGI endpoint and outbound httpx client are real, while route configuration is a fixture.

## Mutation evidence and task clarifications

| Ledger | RED | Equivalent | Recorded source |
|---|---:|---:|---|
| EMB-01 | 33 | 3 | `9c054a3` |
| SEC-01a | 41 | 0 | `9c054a3` |
| THINK-01 | 10 | 0 | `a9d07bf` |
| SEC-01b | 10 | 0 | `a9d07bf` |
| BUILD-01 | 23 | 0 | `a9d07bf` |
| PREP-01 | 29 | 0 | `a9d07bf` |
| Total | 146 | 3 | |

EMB and SEC-01a were rerun in separate clean checkouts; all preflight/restored checks pass. The SEC build-named alias is an identical copy of the same run, not a seventh suite. The four unaffected historical ledgers retain their actual source commit; their recorded source files are unchanged and all six ledgers' blobs are checked against the current tree.

- K-30 removes both normalized/decoded comparison copies, retaining raw comparison: RED. Removing hex normalization alone is redundant with the requested `unquote` arm and cannot truthfully be recorded as RED.
- K-31a removes both logger registrations: RED on actual TCP/log records. K-31b removes only httpcore registration: RED on the explicit synthetic httpcore signature check. Current real TCP traffic produces the httpx INFO summary; it does not produce that httpcore summary, so the synthetic check is labeled separately.
- K-32 restores `NOW()` in the post-lock owner check: RED on expired progress. K-32e restores only the renewal UPDATE condition: EQUIVALENT because the post-lock owner check rejects the expired lease first. Existing K-05e/K-11e equivalences remain.
- These are **five added rows: four RED and one equivalent**. With the original 31 rows, EMB has **36**, not the task's inconsistent 34. No ERROR/CRASH is counted as RED.
- A separate real-PG experiment confirms that putting `clock_timestamp()` only in the pre-lock WHERE can still return an expired row after waiting. The implementation therefore uses a separate post-lock time read.
- Correction to the task's historical explanation: httpx's INFO summary is emitted for MockTransport responses too. Real TCP strengthens transport coverage; it is not the only way to exercise that log line.

## Reproduction and limits

Set `KIWI_TEST_DATABASE_URL` to a disposable loopback PostgreSQL 16 database. Mutation runners require clean committed checkouts and output paths outside them.

```sh
python scripts/test_kiwi_emb_01.py --patch-only
python scripts/test_kiwi_emb_01.py
node scripts/test_kiwi_emb_01_panel.mjs
python scripts/kiwi_emb_01_knives.py --output /tmp/kiwi_emb_01_knives.json
python scripts/kiwi_sec_01a_knives.py --run --output /tmp/kiwi_sec_01a_knives.json
```

The complete regression command list remains in `.github/workflows/ci.yml`. Exact delivery-head CI, Docker build and dependency-audit results are reported in the PR after that commit runs; older green checks must not be presented as its evidence. Local Docker/optional busybox capabilities were unavailable and are not claimed.

Redaction does not promise arbitrary base64/recursive encodings or every third-party debug-log shape. This filter protects the specified HTTP summary signature; SEC-01a logging-capture expansion remains follow-up work for ERR-01. No production database, real paid provider, VPS/Notion document, deployment gate, backup or pod was exercised. Keep PR #88 Draft, based on `release/kiwi-sync`, pending the owner's acceptance and independent CC review.
