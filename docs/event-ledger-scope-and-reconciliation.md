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

## Known follow-up

W2-05b will add a private scope-aware executor for the five chat-drawer memory tools. Until that follow-up lands, quarantine fails closed, while global and live-project drawer memory operations retain their legacy MCP behavior. W2-05b is required before W2-06a.
