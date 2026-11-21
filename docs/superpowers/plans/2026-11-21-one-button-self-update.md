# One-button Self-update Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the guided connector's build check into one confirmed self-update action that safely fast-forwards only when the configured checkout is behind.

**Architecture:** Keep the existing check and guarded update APIs unchanged. The browser client sequences them: check and render first, then conditionally confirm and submit the identity-bound snapshot to the update endpoint. The separate update button is removed so one primary action owns the workflow.

**Tech Stack:** HTML, browser JavaScript, Python `unittest`, FastAPI-backed existing connector APIs

**Spec:** `docs/superpowers/specs/2026-11-21-one-button-self-update-design.md`

## Global Constraints

- Never update without confirmation.
- Only the existing exact-SHA fast-forward endpoint may mutate the checkout.
- Keep repository selection generic; do not hard-code JSON_CODR or an example repository.
- Do not restart automatically after updating files.

## Review Focus

- Confirmation declined: preserve the checked result and leave the action enabled.
- Current/ahead/dirty/diverged/mismatched checkout: display status without opening update confirmation.
- Scope changes during the async check: discard the stale result and never update.
- Update conflict after confirmation: clear the stale snapshot and require another check.
- Successful update: render the refreshed current state and re-enable checking.

---

### Task 1: Combine check and guarded update interaction

**Files:**
- Modify: `web/source-control.html`
- Test: `test_web_static.py`

**Interfaces:**
- Consumes: `POST /api/github/local/check-build` build snapshot and `POST /api/github/local/update-build` guarded update contract.
- Produces: one `#check-build` action labeled `Check for updates`; no separately visible `#update-build` control.

- [ ] **Step 1: Write the failing static interaction test**

Assert the page contains `Check for updates`, a conditional `result.update_allowed` path, confirmation text for the exact update, identity-bound update fields, and no separate `id="update-build"` button.

- [ ] **Step 2: Run the focused test to verify it fails**

Run: Python 3.14 `-m unittest test_web_static.WebStaticTests.test_source_control_guides_github_login_scope_build_check_and_safe_update`

Expected: FAIL because the old separate update button remains.

- [ ] **Step 3: Implement the combined browser flow**

In the `#check-build` handler, render the check result, return for unsafe/non-behind states, and otherwise call the existing confirmed write helper with the snapshot's project root, repository, branch, SHAs, login, and host. Preserve the result when confirmation returns `null`; render the updated result on success; clear stale state on conflict. Remove all separate update-button state and markup.

- [ ] **Step 4: Run focused and connector regression tests**

Run the static test, then `test_github_auth`, `test_github_cli`, `test_web_static`, `test_run_web`, and the focused GitHub API tests.

Expected: all pass; `git diff --check` exits 0.

- [ ] **Step 5: Commit, push, pull, and live-verify**

Commit the plan, test, and UI change; push the current branch; run `git pull --ff-only`; restart the live supervisor; inspect the connector in the native browser at desktop and narrow width; confirm the configured current/ahead checkout renders safely without mutation.
