# KIWI-SEC-01a-P stage evidence · 2026-09-07

This is patch-stage verification for Draft PR #80, not release authorization.

- Previous reviewed head: `d21b709a7d9f2c5e947d098812fb8565249299b5`.
- Tests-first patch commit: `a447276` (27 methods, 8 named assertion failures, no errors, on the previous implementation). Existing invalid-URL/redirect tests explicitly adopt the requested per-provider error receipt while preserving zero-outbound/zero-follow assertions.
- Implementation and test source head: `3f43e284ef140dc6ab5c6c916e04e45bb678bfd9`.
- Local Python: 27 test methods pass (22 previous + 5 new). Admin secret JS test and all 13 existing regression scripts pass; compileall and diff whitespace checks pass.
- [22-knife ledger](https://github.com/LucieEveille/kiwi-mem/blob/b404e426ca9324bc3bd17d92b31855634ec1fe45/docs/acceptance/evidence/kiwi_sec_01a_knives.json): all RED due to assertion failures, preflight and restored full suite exit 0. Every mutated file was restored byte-for-byte and its restore hash checked.

The ledger's `head` is the measured implementation commit, before the evidence-only commit that adds this file and the ledger. `source_blobs` identifies the exact code, test and knife files; those blobs remain unchanged by the evidence commit. Sentinel strings in assertion excerpts are synthetic test data.

## Added guard and knife mapping

| Requirement | Production path exercised | Knife |
|---|---|---|
| Generic credits do not follow redirects | ASGI endpoint with recorded MockTransport requests | K-SEC-18 |
| Buffered chat upstream errors remain stable | Actual non-stream chat endpoint, 401/500 and JSON/plain text bodies | K-SEC-19 |
| Dream stores a stable failure code | Actual run_dream generator; model raises a sentinel exception; update_dream_log arguments inspected | K-SEC-20 |
| One credit provider cannot abort the others | Three-provider HTTP sequence, generic/OpenRouter failures, timeout/500, and env fallback | K-SEC-21 |
| Nullable error is normal SSE | Actual require_success_event; null passes, error object/type:error rejects | K-SEC-22 |

R-01 isolates query failures inside `_query_credits_entry`; provider-list DB failures remain endpoint errors. The query boundary also catches transport/parse exceptions so timeouts cannot bypass provider isolation. R-02 aligns SSE with the existing buffered/tool-loop truthiness checks.

The new PostgreSQL guard T-SEC-01a-04 creates three real provider rows, queries through the real endpoint with a mocked upstream, verifies five requests and the final provider's balance despite the middle provider's failure, then deletes and verifies removal of the fixture rows. PostgreSQL evidence is from CI; no local PostgreSQL or real model call is claimed.

Remaining fixed-string validation messages and calendar reason-code UX are recorded in KNOWN_ISSUES for ERR-01. No authentication, env fallback, default-address, D-class error cleanup or next-stage work is included.

[Implementation-head CI 34055764942](https://github.com/LucieEveille/kiwi-mem/actions/runs/34055764942) passed: 27 security test methods, admin JS guards, all 13 existing regressions, and **181 permanent PostgreSQL 16 guards**. The disposable database was removed. The final PR head CI is listed on PR #80 after the evidence-only commit.
