# COMPAT-02-A consumer probe

Run the Python guard first; it writes all 18 success/stop captures before making
assertions (including on the intentionally red Stage A implementation):

```sh
KIWI_COMPAT_02A_REPORT=/tmp/kiwi_compat_02a_guards.json \
KIWI_COMPAT_02A_CAPTURE_DIR=/tmp/kiwi_compat_02a_streams \
python scripts/test_kiwi_compat_02a.py
npm ci --prefix scripts/sdk_probe
node scripts/sdk_probe/probe.mjs /tmp/kiwi_compat_02a_streams --output /tmp/kiwi_compat_02a_sdk.json
```

`npm ci` requires public npm registry access; commit the lockfile and use a
supported Node runtime (tested with Node 24). npm aliases pin providers 2.0.62
and 2.0.72. No `ai` package, credentials, model call or running Kiwi server is
needed. The fake fetch returns the unchanged captured SSE bytes.

Each of the 18 cases runs against both versions (36 rows). Pass requires the
expected private event occurrences, zero error parts, concatenated `part.delta`
equal to expected text, exactly one finish with `unified` and `raw` both `stop`.
The P/v2-off/plain control expects `expect_private: []` and zero private frames.
Missing/duplicate cases, absent fields, or missing/extra capture files fail.
Python separately covers true errors and `length`; these are not success cases.

Diagnostics never print the stream or an error's `message`, which can contain
rejected JSON. Errors contain only allowlisted type names and sanitized schema
paths. The JSON report additionally records synthetic expected-result text,
finish parts, capture/lock hashes, and presence booleans for response metadata.
Only use this fixture with the repository's synthetic captures, not private
conversation exports.

A leading private event consumes the SDK response-metadata slot; id/model/time
may be absent without backfill. This accepted boundary is recorded, not a pass
criterion. Provider behavior is not a full Chatbox/Cherry runtime or device
test. `compat_02a_sdk_lock_probe_legacy.json` is a separate historical six-case,
three-environment diagnostic table, not this ticket's acceptance matrix.

The mutation runner only runs Python. These consumer results must never be
reported as per-mutant SDK kills.
