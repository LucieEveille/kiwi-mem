# kiwi-mem Agent Instructions

## Repository role and boundaries

- `kiwi-mem` is the public AGPL-3.0 edition of the memory gateway.
- Prefer bug fixes, security hardening, compatibility fixes, documentation, and tests. Private `ai-memory-gateway` features do not automatically belong here.
- When comparing with another repository, port individual fixes deliberately. Never overwrite whole files, copy private configuration, or expose credentials, private URLs, user data, or private-only product behavior.
- Before pushing, confirm `main.py` still identifies the service as `Kiwi-Mem`.

## Sources of truth

- Product and installation behavior: `README.md` and the current code.
- Known public limitations: `KNOWN_ISSUES.md`.
- Release acceptance mother document: `docs/Release Acceptance.md`.
- Completed release evidence: `docs/acceptance/vX.Y.Z.md`.

Read the relevant source documents before planning or changing behavior. Reports from another agent are leads; verify the real branch, diff, files, tests, and CI yourself.

## Normal change workflow

1. Start from the current remote `main`; confirm the worktree is clean and record the base commit.
2. Use a dedicated branch and Draft PR. Do not push directly to `main`.
3. Write or update a regression test before the fix when the bug can be reproduced deterministically. Obtain a precise failing result on the old implementation.
4. Patch only the required locations. Preserve existing public compatibility unless the user explicitly approves a contract change.
5. Run the existing regression scripts, PostgreSQL behavior guards, and all tests related to the changed area.
6. Review the real diff, run `python -m compileall -q .` and `git diff --check`, and perform a target-changing negative mutation when practical. Restore the clean implementation and rerun the affected tests.
7. Keep local tests, GitHub CI, real PostgreSQL, real model-provider calls, deployment, and production verification as separate evidence. A mock or skipped test must never be reported as proof of a real provider, database, or deployment.
8. Do not merge, tag, publish, deploy, delete remote branches, or mutate production data without explicit user authorization.

## Stage checks versus release acceptance

### Ordinary PR or intermediate stage

- Run the repository's existing CI-equivalent checks and the applicable changed-area tests from section B of `docs/Release Acceptance.md`.
- Report the commands, exact results, test counts, skipped or blocked items, and evidence links in the PR delivery report.
- This is stage verification only. Do not create a version acceptance report and do not claim that a release is accepted unless a concrete release version and target commit have been designated.

### Release candidate or user-requested full acceptance

When a concrete version is being prepared for publication, or the user explicitly requests full release acceptance:

1. Copy `docs/Release Acceptance.md` to `docs/acceptance/vX.Y.Z.md`. Do not edit the mother document while filling a release record.
2. Record the target version, exact target commit, and previous official version before testing. Never invent a version; if it is genuinely unknown, leave the release record uncreated and request the missing decision.
3. Execute every fixed item in section A and every applicable row in section B.
4. Use the four result states exactly:
   - `PASS`: executed and supported by evidence.
   - `FAIL`: executed and failed its stated contract.
   - `BLOCKED`: not executable because an environment, credential, dependency, or prerequisite is missing.
   - `N/A`: allowed only in section B when the release did not touch that area, with a written reason.
5. A fixed item may not be marked `N/A`. Any `FAIL`, `BLOCKED`, or unexecuted fixed item blocks an "allow release" conclusion.
6. Fill the evidence columns with sanitized CI run links, command summaries, SQL results, request-capture summaries, or screenshots. "Ran successfully" without evidence is insufficient.
7. Use disposable Docker projects, databases, and volumes for manual acceptance. Prefix test data as required by the mother document, restore changed configuration, clean all generated data, and prove cleanup. Never clear a real database or connect an older version to the primary acceptance or production database.
8. Never put API keys, DSNs, complete private messages, full prompts, or user identifiers in the repository report. Use unique sentinels and redacted evidence.
9. Complete the final decision section truthfully. The agent may recommend `allow release` or `block release`; only the user gives final release authorization.
10. Commit the completed, sanitized `docs/acceptance/vX.Y.Z.md` with the release-preparation changes so the evidence remains versioned with the repository.

## Acceptance report maintenance

- Keep one report per released version. Do not overwrite an older version's report with evidence from a newer commit.
- If the target commit changes after testing, identify the affected checks, rerun them and their dependencies, update the report, and retain the new commit and evidence. Do not silently carry an old PASS forward.
- A newly discovered reproducible incident should first gain a permanent automated regression guard where possible. Add or refine an A/B checklist item only when future releases need a distinct manual or environment-level check.
- Never delete or renumber existing permanent guard IDs merely to make totals pass.
- Self-verification does not replace independent diff review. Keep construction, independent review, user authorization, and release evidence distinct.

