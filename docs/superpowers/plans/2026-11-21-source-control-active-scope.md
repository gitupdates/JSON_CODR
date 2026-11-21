# Source Control Active Scope Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the local Source Control page an explicit repository-and-branch scope that safely focuses remote history, versioning defaults, and local synchronization feedback.

**Architecture:** Extend the existing GitHub CLI adapter and FastAPI commits route with an optional branch filter. Rework the buildless `source-control.html` interface around one persisted Active Scope state, while keeping local Git operations tied to the inspected checkout and comparing that checkout against the selected remote scope.

**Tech Stack:** Python 3.15, FastAPI, GitHub CLI, HTML/CSS/vanilla JavaScript, unittest/pytest, Playwright CLI.

**Spec:** `docs/superpowers/specs/2026-11-21-source-control-active-scope-design.md`

## Global Constraints

- Keep the page buildless and served by the existing FastAPI application.
- Preserve browser confirmation and request-level confirmation for every write operation.
- Validate and URL-encode repository and branch values at API boundaries.
- Never silently switch or retarget a local checkout.
- Keep credentials local and do not add persistent server state.

## Review Focus

- A remembered repository or branch that no longer exists must fall back to a clear selectable state rather than leaving stale scope.
- Branch names containing `/` must survive API encoding and GitHub CLI forwarding unchanged.
- A repository with zero branches must disable branch-dependent actions and explain the state.
- Local repository or branch mismatch must remain visible and must not prevent safe inspection or fetch.
- A failed request during a repository/branch switch must not display data from the previously selected scope.

---

### Task 1: Branch-filtered remote commit history

**Files:**
- Modify: `web_app/github_cli.py:124`
- Modify: `web_app/app.py:1447`
- Modify: `test_github_cli.py:64`
- Modify: `test_web_api.py:281`

**Interfaces:**
- Produces: `GitHubCLI.commits(owner: str, repository: str, branch: str | None = None) -> list[dict[str, object]]`
- Produces: `GET /api/github/repos/{owner}/{repository}/commits?branch=<name>` with an optional branch query parameter.

- [ ] **Step 1: Write failing adapter tests**

Add assertions that `commits("gitupdates", "sample", "feature/ui")` invokes the GitHub commits endpoint with `sha=feature%2Fui`, while the existing call without a branch retains its current request.

- [ ] **Step 2: Run the adapter test and verify RED**

Run: `python -m pytest test_github_cli.py::GitHubCLITests::test_branch_and_commit_reads_return_only_public_summary_fields -q`

Expected: FAIL because `commits` does not accept the branch argument.

- [ ] **Step 3: Implement the optional branch filter**

Update `GitHubCLI.commits` to validate a supplied branch with `_validated_branch` and include it as the `sha` query parameter passed through `_api_pages`.

- [ ] **Step 4: Write and run the API forwarding test**

Extend the GitHub route fake with `commits(owner, repository, branch=None)` and assert that requesting `?branch=feature%2Fui` forwards `feature/ui` exactly.

Run: `python -m pytest test_web_api.py::WebApiTests::test_github_routes_keep_authentication_server_side_and_require_write_confirmation -q`

Expected: PASS.

- [ ] **Step 5: Run focused backend tests**

Run: `python -m pytest test_github_cli.py test_web_api.py -q`

Expected: The new branch-filter tests pass; unrelated known failures are reported separately.

### Task 2: Persistent Active Scope interface

**Files:**
- Modify: `web/source-control.html:1-640`
- Modify: `test_web_static.py`

**Interfaces:**
- Consumes: branch-filtered commits endpoint from Task 1.
- Produces: `selectedRepository` and `selectedBranch` as the sole remote scope state.
- Produces: persisted keys `json_codr_github_repository` and `json_codr_github_branch`.

- [ ] **Step 1: Write failing static contract tests**

Add assertions that the page contains accessible `repository-select` and `branch-select` controls, an `active-scope-summary` live region, local scope comparison output, branch-filtered commits request construction, and no `Â·` text.

- [ ] **Step 2: Run the static test and verify RED**

Run: `python -m pytest test_web_static.py -q`

Expected: FAIL because `branch-select` and the Active Scope contract do not exist and broken encoding remains.

- [ ] **Step 3: Implement the visual hierarchy and Active Scope panel**

Update the page styles and markup to provide:

- a compact header and introductory copy;
- a visually distinct, optionally sticky Active Scope card;
- searchable/native repository selection plus a branch selector;
- selected repository, branch, visibility/protection, and local match summaries;
- clearer Remote activity, Collaboration, Releases, Local sync, and collapsed Administration sections;
- responsive stacking below 720px, visible focus states, and at least 14px task labels/16px body copy.

- [ ] **Step 4: Implement scope state and branch loading**

On repository selection, clear stale rendered data, load branches, restore the remembered branch only if present, otherwise prefer the repository default branch, and disable branch-sensitive controls if no branch exists. On branch selection, persist it and refresh branch-filtered commit data.

- [ ] **Step 5: Apply scope to collaboration and versioning defaults**

Default PR base, remote branch source, and release target to `selectedBranch.name`; keep user-edited values unless the repository changes. Include the exact repository and branch in write confirmations.

- [ ] **Step 6: Add local/remote comparison and sync safety copy**

Compare `localSnapshot.repository` and `localSnapshot.branch` with Active Scope, render matched/repository-mismatch/branch-mismatch states, and keep operations bound to `localSnapshot.project_root`. Disable push and pull when a selected remote scope exists but does not match the inspected local repository/branch; keep inspect and fetch available.

- [ ] **Step 7: Repair text encoding and request-state behavior**

Replace all mojibake separators with valid UTF-8 punctuation, use section-specific live status regions, prevent stale responses from a prior scope from replacing the current scope, and restore buttons after failures.

- [ ] **Step 8: Run static and focused web tests**

Run: `python -m pytest test_web_static.py test_web_api.py::WebApiTests::test_github_routes_keep_authentication_server_side_and_require_write_confirmation -q`

Expected: PASS.

### Task 3: Live browser verification and regression check

**Files:**
- Modify only if verification reveals a defect: `web/source-control.html`, corresponding tests.

**Interfaces:**
- Consumes: completed Task 1 API and Task 2 UI.
- Produces: browser-verified local Source Control experience at `http://127.0.0.1:8765/static/source-control.html`.

- [ ] **Step 1: Run focused automated tests**

Run: `python -m pytest test_github_cli.py test_web_static.py test_web_api.py -q`

Expected: New scope tests pass; every unrelated pre-existing failure is named in the handoff.

- [ ] **Step 2: Open and inspect the live page**

Use Playwright CLI to open the supplied URL, capture a snapshot, and verify there are no page or console errors on initial load.

- [ ] **Step 3: Exercise scope selection**

Select a repository and a non-default branch where available. Verify the Active Scope summary, branch-filtered commits request, PR/release defaults, remembered selection after reload, and stale-data clearing while loading.

- [ ] **Step 4: Exercise local mismatch states**

Inspect the current checkout and verify matched scope. Select a different remote branch and verify the mismatch warning and push/pull gating without changing the checkout.

- [ ] **Step 5: Verify narrow layout**

At approximately 390px viewport width, confirm selectors, action buttons, status cards, and long repository/branch names remain readable without horizontal page scrolling.

- [ ] **Step 6: Run the complete suite**

Run: `python -m pytest -q`

Expected: All new and changed tests pass. Report the exact total and identify any failures that predate or fall outside this plan.

- [ ] **Step 7: Inspect the final diff**

Run: `git diff --check` and `git diff --stat`.

Expected: no whitespace errors; changes are limited to the design/plan, branch-filter API/tests, and Source Control UI/tests.

