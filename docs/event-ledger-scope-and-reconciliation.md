# Event ledger scope and read-only reconciliation

W2-05 defines how a chat request chooses one immutable scope and how operators audit the event ledger without rewriting history.

## Shared base and private project layer

Global semantic memories, locked memories, calendar pages, and Dream scenes form a shared base. A live project adds its own instructions, files, memories, handoff source, and conversations. Project-private content never flows into global chats or another project.

The ledger's historical attribution and the request's current read authorization are deliberately separate. A conversation may still be historically attributed to a deleted project while the current request is forbidden from reading that project's orphaned rows.

## Request scope modes

Every `/v1/chat/completions` request resolves one five-field snapshot before prompt construction, tool routing, provider calls, or ledger writes:

- `global`: write a known-global ledger scope and read only the shared base. Conversation search uses the existing `"none"` sentinel to mean global-only.
- `live_project`: write the live project ID and read the shared base plus that project's private layer.
- `quarantined_project`: used for deleted or unverified project identities. It preserves any provable historical ledger attribution, reads only the shared base, hides memory/conversation drawer categories, disables project handoff, and skips automatic extraction with `skip_unverified`.

Missing or explicit-null `project_id` means global. A non-empty project ID must exist before it can grant project reads. Invalid request shapes are rejected with `invalid_project_id` before provider or database work.

The snapshot is reused when the response is written to the ledger. Tombstones and reset generation are still rechecked inside the write transaction, but scope is not recomputed after model generation.

## Historical rows

W2-05 does not backfill old ledger rows. Rows with `scope_known = FALSE` remain a historical archive and are excluded from future scope-aware readers. This avoids guessing project or turn identity from incomplete historical material.

## Reconciliation

Run:

```bash
python scripts/ledger_reconcile.py --json
```

The command opens one PostgreSQL `REPEATABLE READ, READ ONLY` snapshot, counts the entire selected ledger, and limits only the returned integer ID samples. It never returns message bodies, session IDs, project IDs, API keys, or DSNs.

Exit codes are:

- `0`: every unexplained bucket is empty;
- `2`: at least one unexplained bucket is non-zero;
- `64`: invalid command arguments.

Three survivor buckets have priority over every benign explanation: rows that remain after a matching session, turn, or message tombstone. Other explained buckets require exact database evidence or are explicitly marked weak. A non-zero unexplained bucket blocks a consumer cutover; it does not modify the database.

## Chat-drawer memory scope (W2-05b)

The W2-05b implementation closes the drawer scope follow-up on the integration branch, pending acceptance and release. The shared global collection remains a foundation visible inside every live project; a project's private layer is visible only inside that project. This one-way boundary lets projects recall shared facts without exposing another project's memories.

The five drawer tools (`search_memory`, `save_memory`, `get_recent`, `lock_memory`, `unlock_memory`) use a private database executor after the existing quarantine check. Global scope (including `scope=None`) reads only global memories; a live project reads global plus its own memories. Search/recent totals and the post-save total use that same collection, exclude digested, deleted and expired memories, and do not shrink with the result limit. Saves write to the current project, or to global when there is no project.

Lock/unlock uses one scope-filtered `UPDATE … RETURNING`: live projects may change their own and global memories. A user lock atomically writes `lock_source='user'`; the retirement task itself does not select rows while that source remains `user`. Until [KIWI-LOCK-01](../KNOWN_ISSUES.md#kiwi-lock-01) is fixed, however, Dream's promote action overwrites the source with `dream`, after which stale-lock retirement removes the lock when its retirement conditions are met (the memory is not deleted). Explicit unlock clears the source. Missing and out-of-scope IDs share one refusal message without a reason lookup. Boolean and string IDs are refused. Content/title are stripped for storage, importance is clamped to 1–10, and result limits to 1–50. Tool failures emit one redacted `drawer_memory_tool_failed` event and a fixed result.

These drawer calls no longer loop back through `GATEWAY_BASE` or `/debug/*`; the existing embedding provider calls within search/save remain. The public MCP still exposes six tools (including `trigger_digest`); the drawer still discovers the same five memory schemas in the same order. Public MCP functions, the three debug handlers, old database calls without `visible_scope`, and W2-05 quarantine/routing behavior retain their existing contracts.

Database callers opt in using keyword-only `visible_scope=("global", None)` or `("live_project", project_id)`; combining this with `project_id`, or passing an invalid/quarantined scope, raises `ValueError`. Evidence: frozen `T-W2-05b-01…07` real-PG16 guards and `docs/acceptance/evidence/kiwi_w2_05b_knives.json` (13 mutations). This closes the implementation debt required before W2-06a; it does not authorize consumer cutover or deployment.
