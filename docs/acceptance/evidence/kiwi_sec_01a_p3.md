# KIWI-SEC-01a-P3 stage evidence · 2026-09-07

This is a narrow repair within Draft PR #80, starting at `7b3d5d639239668155872d82e32ce23578475ccc`. Independent review found that the real Anthropic adapter discarded non-SSE bodies and emitted only DONE. P2's injected-adapter test did not prove the complete path; this stage replaces it with raw upstream fixtures passing through the real adapter. Release acceptance remains pending.

## Tests-first and implementation

- Tests-only commit `69e6e85`: 37 methods against the previous runtime produced **6 assertion failures, zero errors**. JSON error, HTML and buffered success JSON each fail with and without terminating newlines because parse_failed is missing. Valid Anthropic events, in-band error handling, empty-body compatibility and the added buffered type:error case already pass on the old runtime.
- Implementation / measured source head: `2550a5288165227f0319c4bd49873f4b03aff082`. Runtime changes are seven added lines in `anthropic_stream_to_openai`: track received byte count and successful data-line parsing, then raise UpstreamFailure("parse_failed") before the fallback DONE when bytes were received but no data was parsed. Outer safe_sse creates the error frame and one DONE. Existing read-exception handling and gateway branches are unchanged.
- Empty upstream bodies keep their existing completion behavior. Other malformed SSE shapes and billing /v1/messages suffix behavior remain recorded in KNOWN_ISSUES, outside this repair.

## Verification

- **37/37** security test methods pass. The actual ASGI chat request uses MockTransport for the upstream /v1/messages response; request capture asserts the path and stream=true. The helper no longer permits replacing the adapter.
- All three non-SSE bodies, each with/without terminating newlines: exactly one parse_failed error frame, exactly one DONE, no choices, sentinel windows absent.
- A real Anthropic event sequence includes keepalive, id/retry, ping, message_start, two text deltas and message_stop: exact combined content part-one, zero errors, one DONE. Real event:error after those text deltas preserves prior content and emits one stable upstream_error and one DONE.
- Buffered HTTP 200 {"type":"error","error":null,"message":sentinel}: HTTP 502 with exactly the stable upstream_error shape and no sentinel.
- Separate adapter-level MockTransport probe: the three raw non-SSE bodies raise parse_failed; empty body emits only DONE; valid events complete normally.
- Existing regression scripts and all three Node guards pass, including test_admin_secrets.mjs. compileall and diff --check pass.
- [Measured-source CI 34064892320](https://github.com/LucieEveille/kiwi-mem/actions/runs/34064892320): 37 security methods and **183 PostgreSQL 16 permanent guards** pass; disposable DB removal confirmed. The PG guard file and counts are unchanged. Final evidence-only head CI is tracked in PR #80.

## Mutation evidence and provenance

[41-knife ledger](kiwi_sec_01a_knives.json): **41/41 RED**, preflight=0, restored_suite=0. Every case is a named assertion failure, not a crash; exact bytes are restored after each mutation. The measured head is `2550a52`; source_blobs now contains seven files including anthropic_adapter.py. The subsequent evidence-only commit must match all seven source blobs.

| Knife | Mutation | Guard | Recorded red reason |
|---|---|---|---|
| K-SEC-40 | Remove the adapter's parse_failed raise | test_adapted_stream_rejects_non_sse_event | AssertionError: Lists differ: [] != [{'error': 'parse_failed', 'error_code': 'parse_failed'}] |
| K-SEC-41 | Remove only buffered type == error check | test_buffered_chat_200_error_is_not_success | AssertionError: 200 != 502 |

K-SEC-01 through 39 were rerun with the updated suite. In-band Anthropic coverage now also traverses the real adapter. The prior [39-knife ledger](https://github.com/LucieEveille/kiwi-mem/blob/7b3d5d639239668155872d82e32ce23578475ccc/docs/acceptance/evidence/kiwi_sec_01a_knives.json) and P2 records remain historical evidence, not a claim that P2 already fixed this defect.

Upstream HTTP/model boundaries are mocked; PostgreSQL is real in CI, not on the local workstation. No real provider, browser reacceptance, production, deployment, or release authorization is claimed. The PR stays Draft pending independent replay; integration-branch creation, PR-base change and publication are separate user decisions.
