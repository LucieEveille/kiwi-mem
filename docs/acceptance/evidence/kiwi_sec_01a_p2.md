# KIWI-SEC-01a-P2 stage evidence · 2026-09-07

P2 is a repair stage within Draft PR #80. The prior reviewed head was `b404e426ca9324bc3bd17d92b31855634ec1fe45`; this record does not authorize release.

## Changes and reproduction

- Tests-first commit `358ca9c`: 37 methods on the old implementation produced **28 assertion failures, zero errors**. The failures reproduce changed credit origins and path segments, non-SSE bodies reaching clients, DEL acceptance and invalid provider credential types.
- Runtime implementation `5a0226495a37b93614446bf5992f937f337a4861`: generic credit roots only edit the parsed path (remove the chat/completions suffix and an exact final v1 segment), then append it to the validated origin. Host, scheme and port are preserved. DEL is rejected. Provider creation rejects non-string credentials with HTTP 400.
- Both stream_and_capture branches check SSE event prefixes before inspecting or forwarding events and tails. Non-SSE bodies end with parse_failed and one DONE. Content-Type is deliberately not used; comments, event/id/retry fields and error:null remain compatible.
- Measured source/test head: `b96ec0d0f05536b17588cb417c9804f9442fcb92`. Its only change after the runtime implementation isolates per-arm test fixtures: a destructive clear mutation previously caused one valid assertion failure followed by a poisoned-fixture KeyError, correctly classified CRASH. After fixture isolation, all 39 mutations were rerun; no CRASH is counted as RED.

## Verification scope

- **37** SEC test methods (27 previous + 10 new) pass. All 13 existing regression scripts and the admin secret Node test pass. Python compileall and diff whitespace checks pass.
- Credit matrix: 9 base URLs through both DB-provider and env routes, including v1/v10/v1-api hostnames, v1beta/v10 path segments, explicit ports and IPv6. Each actual MockTransport request asserts scheme/host/port, full billing path and Authorization.
- Stream tests use the actual HTTP chat entry with fake DB reads, disabled memory/reminder tools and mcp_mode=off; captured upstream bodies assert stream=true, proving the direct stream path was exercised. JSON error / HTML / buffered-success JSON bodies are tested with and without an event terminator. In-band errors preserve prior content and end with a stable error and one DONE.
- The Anthropic post-adapter prefix/error checks are exercised by an injected adapter generator emitting malformed or in-band-error events. This proves the four downstream checks; it is not a claim that a real Anthropic upstream emits that malformed adapter output. Existing adapter behavior tests remain green.
- PostgreSQL 16: **183** permanent guards (181 previous + T-SEC-01a-05/06), including real saved-provider rows for the six required URL shapes and a null-credential POST that leaves no new DB row. Fixture rows and the disposable DB are removed. [Runtime CI 34060623524](https://github.com/LucieEveille/kiwi-mem/actions/runs/34060623524) confirms these results; final-head CI is tracked in PR #80.
- Real model/API calls, production, browser reacceptance and deployment were not performed. HTTP/model boundaries are mocked; real PostgreSQL evidence comes from CI, not the local workstation.

## Branch coverage added after independent review

The mutations below map one-to-one to the 17 independently identified gaps. K-SEC-32 deliberately removes two in-band event checks together, exactly matching the reviewed mutation; the runner requires exactly two anchors for this case and exactly one for every other case. Every RED is an AssertionError in its named test, with no ERROR result.

| Review branch | Knife | Behavior protected | Test method | Result |
|---|---|---|---|---|
| KX-01 | K-SEC-23 | Control-character rejection | `test_url_rejection_matrix_and_hostname_dispatch` | RED |
| KX-02 | K-SEC-24 | Backslash rejection | `test_url_rejection_matrix_and_hostname_dispatch` | RED |
| KX-03 | K-SEC-25 | Port zero rejection | `test_url_rejection_matrix_and_hostname_dispatch` | RED |
| KX-04 | K-SEC-26 | Empty port rejection | `test_url_rejection_matrix_and_hostname_dispatch` | RED |
| KX-05 | K-SEC-27 | Exact hostname versus suffix confusion | `test_url_rejection_matrix_and_hostname_dispatch` | RED |
| KX-06 | K-SEC-28 | Duplicate secret metadata keys | `test_invalid_meta_rejected_before_any_write` | RED |
| KX-07 | K-SEC-29 | Extra metadata fields | `test_invalid_meta_rejected_before_any_write` | RED |
| KX-08 | K-SEC-30 | clear:false rejection | `test_clear_contract_and_not_found_status` | RED |
| KX-09 | K-SEC-31 | not_found remains HTTP 404 | `test_clear_contract_and_not_found_status` | RED |
| KX-10 | K-SEC-32 | In-band stream errors in both event loops | `test_direct_stream_inband_error_preserves_prior_content` | RED |
| KX-11 | K-SEC-33 | Buffered HTTP 200 error objects | `test_buffered_chat_200_error_is_not_success` | RED |
| KX-12 | K-SEC-34 | Credit dispatch versus URL substring | `test_url_rejection_matrix_and_hostname_dispatch` | RED |
| KX-13 | K-SEC-35 | Provider PUT URL validation | `test_provider_url_and_credential_inputs_reject_before_write` | RED |
| KX-14 | K-SEC-36 | Provider POST URL validation | `test_provider_url_and_credential_inputs_reject_before_write` | RED |
| KX-15 | K-SEC-37 | Search-config clear rejection | `test_clear_contract_and_not_found_status` | RED |
| KX-16 | K-SEC-38 | OpenRouter second-path failure | `test_second_credit_path_failure_is_not_success` | RED |
| KX-17 | K-SEC-39 | Generic second-path failure | `test_second_credit_path_failure_is_not_success` | RED |

The root-construction bug and non-SSE-body bug also have tests-first failing reproductions above; the new knife set remains exactly the requested 22 + 17 = **39**.

## Ledger provenance

[P2 39-knife ledger](https://github.com/LucieEveille/kiwi-mem/blob/7b3d5d639239668155872d82e32ce23578475ccc/docs/acceptance/evidence/kiwi_sec_01a_knives.json): head is the measured source commit `b96ec0d`, six source_blobs are frozen, preflight=0, restored_suite=0, 39/39 RED. Mutations restore exact original file bytes and verify their SHA-256 after every case. The subsequent evidence-only commit changes this record, the JSON ledger and the historical P1 evidence link; all six tested source blobs remain identical. The [previous 22-knife ledger](https://github.com/LucieEveille/kiwi-mem/blob/b404e426ca9324bc3bd17d92b31855634ec1fe45/docs/acceptance/evidence/kiwi_sec_01a_knives.json) remains available at its original revision.

Out-of-scope input JSON status mapping, unknown error-code status consistency and legacy fixed strings are recorded in KNOWN_ISSUES for ERR-01. Authentication, env fallback, default upstream addresses, remaining D-class exits, stream chunking behavior and dependency adaptation are unchanged. Independent replay and user acceptance remain pending.
