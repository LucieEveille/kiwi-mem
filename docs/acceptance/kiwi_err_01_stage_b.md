# KIWI-ERR-01 stage B evidence — 2026-09-20

Status: implementation delivered for independent stage-B acceptance. PR #89 stays Draft; no merge, deployment, production verification or release approval.

## Revisions

- Integration base: `231b3ebd32e7e1775d4969e60f12c2e694528356`.
- Stage A: `1632db2dd01d68a27397901d57e89b4418973f00`, tests only.
- Stage A2: `743bd277d61da54cf301f4632acb5ccb23e02260`, tests only; 337 cases, 314 expected failures, 23 continuation passes, zero errors.
- Implementation: `ff11f3a5c46c36d183d7dbdc7fa9a812259d4f9d`, tree `e2ad82410ada8293b2820ee48f3e87863ced1dbf`.
- This evidence-only commit changes no pinned implementation/test files. Each ledger points to the implementation commit; source_blobs must also match the PR tip.

## Behavior and tests

The enumerated HTTP exceptions now use stable error codes/statuses. Optional empty bodies remain valid while malformed nonempty JSON/UTF-8 returns 400. Background failure dictionaries/logs are bounded, and HTTP/1.1 DEBUG reason phrases are redacted. Existing W2 responses, nested reasoning diagnostics, calendar format failures and embedding probe semantics remain explicit exceptions; see UPGRADING and security-model.

- Windows and Linux: 338 new guard cases, all pass; includes the 37-case SEC logging calibration subprocess. Stage A2's 150 exception cases recorded the actual target return line before asserting response behavior.
- Existing regression scripts: 19 Python plus 4 Node passed. Includes PG16 safety 184, PREP 13, BUILD 13, SEC-01a 37, SEC-01b 12, THINK 12, EMB 19 plus panel 7, and compression reasoning.
- CI on the implementation commit: [run 35456024519](https://github.com/LucieEveille/kiwi-mem/actions/runs/35456024519), all jobs/steps successful, including image build, dependency audit, guards and mutations.
- Syntax compilation, diff whitespace check, and unchanged-scope audit passed. The latter checks stable_payload/exception_code/public_dream_record, the non-string reasoning branch, daily SQL, W2 response blocks, database/embedding files, old reasoning guard, panel and VERSION.

## Mutation evidence

All seven suites below were rerun on the public implementation commit in a clean disposable checkout. Preflight and restored suites returned zero; restoration checks passed. CRASH is never RED, and K-10 equivalence is observed from its successful 37-case run, not inferred from an ID suffix.

| Suite | Executions | Observed | Pinned blobs |
| --- | --- | --- | --- |
| err_01 | 12 | {'RED': 11, 'EQUIVALENT': 1} | 11 |
| sec_01a | 41 | {'RED': 41} | 7 |
| prep_01 | 29 | {'RED': 29} | 17 |
| build_01 | 23 | {'RED': 23} | 9 |
| sec_01b | 10 | {'RED': 10} | 6 |
| think_01 | 10 | {'RED': 10} | 6 |
| emb_01 | 36 | {'RED': 33, 'EQUIVALENT': 3} | 15 |

Total source_blobs entries checked against the implementation tree: 71. SEC's historical `kiwi_sec_01a_build_knives.json` alias is synchronized to the same SEC result; eight JSON files represent seven distinct suites.

## Calibration notes and boundaries

- PG T-S6-5 previously expected HTTP 200 after an injected Dream database failure. ERR-01's approved D20 contract changes that to HTTP 500. The assertion now checks the exact two-key internal_error body; both real transaction rollback assertions remain unchanged. Missing/repeated Dream deletion behavior and W2 fixed responses are untouched.
- EMB K31a/K31b anchors follow the expanded logger registration tuple; their mutations remain "remove all filters" and "retain only httpx".
- New ASGI tests use fake storage/providers. HTTP/1.1 uses actual local TCP; HTTP/2 uses synthetic Trace. Daily log statements are exercised independently, not as a complete scheduler run. PG184/EMB use disposable local PG16 databases; no production or real provider calls.
- Local PREP optional BusyBox and real Compose probes were unavailable. CI separately passed the framework/image build and audit steps. Do not interpret this as full release/production acceptance.
- A user-requested pause stopped local PG before the last public-head EMB preflight. That environmental connection refusal is preserved in the external delivery evidence; it was not counted as a mutation kill. EMB was rerun successfully after resume.

Independent stage-B acceptance and a clean adversarial review are still required before Ready/backup/Squash/deployment. No W2-05b work was run in parallel.
