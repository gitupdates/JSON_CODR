# GitHub Connector Build Update Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a generic guided GitHub connection that authenticates through GitHub CLI, selects a repository and branch, compares an explicitly connected local checkout with that branch, and performs only confirmed safe fast-forward updates.

**Architecture:** Add an in-memory GitHub CLI browser-login session service beside the existing synchronous `GitHubCLI` adapter. Extend `GitHubCLI` with selected-scope build comparison and stale-safe update methods, expose both capabilities through confirmed FastAPI request models, and reorganize the buildless Source Control page around one progressive connection panel while preserving advanced controls.

**Tech Stack:** Python 3.15, FastAPI, Pydantic, GitHub CLI, Git CLI, HTML/CSS/vanilla JavaScript, unittest/pytest.

**Spec:** `docs/superpowers/specs/2026-11-21-github-connector-build-update-design.md`

## Global Constraints

- Support the active `github.com` GitHub CLI identity only; do not add GitHub Enterprise or multi-account switching.
- Never receive, store, log, or return GitHub credentials or personal access tokens.
- Do not hard-code or specially handle the example repository shown in the user's reference image.
- Keep the page buildless and served by the existing FastAPI application.
- Require the `X-JSON-CODR: 1` header on every connector route.
- Require browser confirmation and `confirmed: true` for login, fetch/check, cancellation, and update operations.
- Run Git and GitHub CLI commands as argument arrays without a shell.
- Never reset, clean, rebase, force-update, switch branches, or change upstream configuration.
- Update only by merging the exact validated `refs/remotes/origin/<selected-branch>` ref with `--ff-only` after refetching and revalidating state.

## Review Focus

- A GitHub CLI login process that hangs, closes its browser, emits partial output, or outlives app shutdown must terminate without leaking a process or code.
- A repository/branch/path selection changed after a check must make the previous result ineligible for update.
- Branch names containing `/`, spaces, control characters, or ref syntax must be validated and passed as individual arguments; valid slash names must work.
- Remote movement, local movement, dirty state, divergence, repository mismatch, or branch mismatch between check and update must abort before merge.
- A local branch with no configured upstream must still compare and safely update against the explicitly selected matching remote branch without creating an upstream.

---

### Task 1: In-memory GitHub browser-login sessions

**Files:**
- Create: `web_app/github_auth.py`
- Create: `test_github_auth.py`

**Interfaces:**
- Produces: `GitHubAuthSessionService.start() -> dict[str, object]`
- Produces: `GitHubAuthSessionService.status(session_id: str) -> dict[str, object]`
- Produces: `GitHubAuthSessionService.cancel(session_id: str) -> dict[str, object]`
- Produces: `GitHubAuthSessionService.close() -> None`
- Produces terminal states `authenticated`, `failed`, `cancelled`, and `expired`; active states `starting` and `waiting`.

- [ ] **Step 1: Write failing login-session lifecycle tests**

In `test_github_auth.py`, use an injected fake process factory and clock to assert:

- `start()` invokes `gh auth login --web --hostname github.com --git-protocol https` as an argument list and returns a generated session ID in `starting` state;
- a second `start()` while active raises `GitHubAuthSessionConflict`;
- streamed output containing a device code exposes only that code and `https://github.com/login/device` while state is `waiting`;
- a zero exit followed by an injected authenticated status probe yields `authenticated` without returning raw process output;
- nonzero exit, timeout, cancellation, and `close()` terminate the process and produce the correct sanitized terminal state;
- session IDs are required and terminal sessions expire from memory after the configured retention period;
- strings matching GitHub token patterns are redacted from all returned detail.

- [ ] **Step 2: Run the test and verify RED**

Run: `python -m pytest test_github_auth.py -q`

Expected: FAIL because `web_app.github_auth` does not exist.

- [ ] **Step 3: Implement the session service**

Implement `GitHubAuthSessionService` with injected executable finder, `subprocess.Popen` factory, authentication status probe, monotonic clock, timeout, and retention settings. Protect the one-active-session invariant with a lock; use one daemon worker per login to read combined output, send the newline required to continue the web flow, parse only the one-time device code, transition state, enforce timeout/cancel, and discard raw output. Define `GitHubAuthSessionNotFound` and `GitHubAuthSessionConflict` for API mapping.

- [ ] **Step 4: Run focused tests and verify GREEN**

Run: `python -m pytest test_github_auth.py -q`

Expected: PASS with no live child process left by any test.

- [ ] **Step 5: Commit the authentication service**

```bash
git add web_app/github_auth.py test_github_auth.py
git commit -m "feat: add GitHub browser login sessions"
```

### Task 2: Authentication API contracts and lifecycle wiring

**Files:**
- Modify: `web_app/models.py:681`
- Modify: `web_app/app.py:35,108,179,1297`
- Modify: `test_web_api.py:281`

**Interfaces:**
- Consumes: `GitHubAuthSessionService` from Task 1.
- Produces: `POST /api/github/auth/login`
- Produces: `GET /api/github/auth/login/{session_id}`
- Produces: `POST /api/github/auth/login/{session_id}/cancel`
- Produces: optional `github_auth` dependency injection in `create_app(...)` and shutdown cleanup.

- [ ] **Step 1: Write failing authentication API tests**

Add a fake auth service to `test_web_api.py` and assert:

- all three routes reject a missing `X-JSON-CODR` header;
- login start and cancellation reject missing `confirmed: true`;
- confirmed requests forward once to the injected service;
- status returns active and terminal safe fields, including the optional device code and fixed verification URL;
- not-found maps to HTTP 404 and active-session conflict maps to HTTP 409;
- application shutdown invokes `close()`.

- [ ] **Step 2: Run the API test and verify RED**

Run: `python -m pytest test_web_api.py::WebApiTests::test_github_authentication_session_routes_are_confirmed_and_server_managed -q`

Expected: FAIL because `create_app` has no auth service and the routes do not exist.

- [ ] **Step 3: Add request models and routes**

Add `GitHubAuthLoginRequest(GitHubConfirmedWrite)` and `GitHubAuthCancelRequest(GitHubConfirmedWrite)` to `web_app/models.py`. Inject or construct `GitHubAuthSessionService` in `create_app`, add the three routes beside `/api/github/status`, map session exceptions explicitly, and register `close()` on application shutdown.

- [ ] **Step 4: Run API and auth tests and verify GREEN**

Run: `python -m pytest test_github_auth.py test_web_api.py::WebApiTests::test_github_authentication_session_routes_are_confirmed_and_server_managed -q`

Expected: PASS.

- [ ] **Step 5: Commit the authentication API**

```bash
git add web_app/models.py web_app/app.py test_web_api.py
git commit -m "feat: expose confirmed GitHub login flow"
```

### Task 3: Selected-scope build comparison and safe update

**Files:**
- Modify: `web_app/github_cli.py:267-390`
- Modify: `test_github_cli.py:153`

**Interfaces:**
- Produces: `GitHubCLI.check_build(project_root: str, repository: str, branch: str) -> dict[str, object]`
- Produces: `GitHubCLI.update_build(project_root: str, repository: str, branch: str, expected_local_sha: str, expected_remote_sha: str) -> dict[str, object]`
- Produces: `GitHubBuildConflict(GitHubCLIError)` with HTTP-compatible status code 409 for state that changed after a check.
- Produces build statuses `current`, `behind`, `ahead`, `diverged`, `local_changes`, `repository_mismatch`, `branch_mismatch`, `detached`, `remote_missing`, and `unavailable`.

- [ ] **Step 1: Write failing build-comparison tests**

Extend `test_github_cli.py` with isolated temporary repositories and/or an argument-recording runner. Assert that `check_build`:

- validates `owner/repository` and branch values;
- verifies the local GitHub origin and current branch against the explicit selection;
- fetches only `+refs/heads/<branch>:refs/remotes/origin/<branch>`;
- computes current, behind, ahead, and diverged from `HEAD...refs/remotes/origin/<branch>`;
- returns safe local/remote commit SHA, short SHA, subject, author name, authored timestamp, dirty flag, ahead/behind counts, checked-at timestamp, status, detail, `update_allowed`, and `update_blocked_reason`;
- reports dirty, detached, repository mismatch, branch mismatch, and missing remote branch without merging;
- treats missing upstream as informational when origin and current branch match the explicit selection.

- [ ] **Step 2: Run comparison tests and verify RED**

Run: `python -m pytest test_github_cli.py -k "build_comparison" -q`

Expected: FAIL because `check_build` does not exist.

- [ ] **Step 3: Implement `check_build` and focused helpers**

Add selected-scope parsing, exact remote-ref fetch, commit-detail extraction, relationship calculation, and deterministic status precedence. Reuse `_local_repository`, `_validated_branch`, `_ahead_behind`, and `_git`; keep all response fields display-safe.

- [ ] **Step 4: Run comparison tests and verify GREEN**

Run: `python -m pytest test_github_cli.py -k "build_comparison" -q`

Expected: PASS.

- [ ] **Step 5: Write failing stale-safe update tests**

Add tests asserting that `update_build` refetches and recomputes all safety facts, then:

- merges the exact remote-tracking ref with `git merge --ff-only` only for a clean, matching, strictly-behind checkout with zero local-ahead commits;
- returns the refreshed current build result after success;
- raises `GitHubBuildConflict` for changed local SHA, changed remote SHA, dirty state, divergence, ahead state, repository/branch mismatch, detached HEAD, and missing remote branch before merge;
- never runs reset, clean, checkout, switch, rebase, force, or upstream-changing commands.

- [ ] **Step 6: Run update tests and verify RED**

Run: `python -m pytest test_github_cli.py -k "build_update" -q`

Expected: FAIL because `update_build` does not exist.

- [ ] **Step 7: Implement `update_build`**

Validate both expected SHAs as 40- or 64-character hexadecimal object IDs, invoke the same internal comparison used by `check_build`, reject stale or blocked state with a sanitized `GitHubBuildConflict`, run `merge --ff-only` only after every invariant passes, and return a fresh post-update comparison without changing upstream configuration.

- [ ] **Step 8: Run the full GitHub CLI adapter test and verify GREEN**

Run: `python -m pytest test_github_cli.py -q`

Expected: PASS, including existing fetch/pull behavior.

- [ ] **Step 9: Commit build comparison and update**

```bash
git add web_app/github_cli.py test_github_cli.py
git commit -m "feat: compare and safely update selected builds"
```

### Task 4: Build check and update API

**Files:**
- Modify: `web_app/models.py:783`
- Modify: `web_app/app.py:1547`
- Modify: `test_web_api.py:335`

**Interfaces:**
- Consumes: `GitHubCLI.check_build(...)` and `GitHubCLI.update_build(...)` from Task 3.
- Produces: `GitHubBuildCheckRequest` and `GitHubBuildUpdateRequest`.
- Produces: `POST /api/github/local/check-build`
- Produces: `POST /api/github/local/update-build`

- [ ] **Step 1: Write failing build API tests**

Add fake adapter methods and assert both endpoints:

- require `X-JSON-CODR: 1` and `confirmed: true`;
- validate project path length, `owner/repository`, branch length, and expected SHA shapes at the request boundary;
- forward project root, repository, branch, and expected SHAs exactly once;
- preserve the existing 403/409/422/502 error mapping without exposing raw command data;
- return only the adapter's safe comparison result.

- [ ] **Step 2: Run the API test and verify RED**

Run: `python -m pytest test_web_api.py::WebApiTests::test_github_build_check_and_update_require_confirmation_and_exact_scope -q`

Expected: FAIL because the models and routes do not exist.

- [ ] **Step 3: Add request models and routes**

Add `GitHubBuildCheckRequest(GitHubConfirmedWrite)` with `project_root`, an exact `owner/repository` pattern, and `branch`, plus `GitHubBuildUpdateRequest(GitHubBuildCheckRequest)` with 40- or 64-character hexadecimal `expected_local_sha` and `expected_remote_sha`. Add the two confirmed routes near existing local GitHub operations and delegate through `github_call`; `GitHubBuildConflict` maps to HTTP 409 through its existing `GitHubCLIError` boundary.

- [ ] **Step 4: Run focused backend tests and verify GREEN**

Run: `python -m pytest test_github_cli.py test_github_auth.py test_web_api.py -k "github" -q`

Expected: PASS.

- [ ] **Step 5: Commit the build API**

```bash
git add web_app/models.py web_app/app.py test_web_api.py
git commit -m "feat: expose GitHub build update API"
```

### Task 5: Progressive GitHub connection panel

**Files:**
- Modify: `web/source-control.html:1-640`
- Modify: `test_web_static.py`

**Interfaces:**
- Consumes authentication, repository, branches, check-build, and update-build endpoints from Tasks 2 and 4.
- Produces browser preference keys scoped by authenticated login for repository, branch, and local path.
- Produces one current `connectionState` containing account, repository, branch, checkout, and last build comparison.

- [ ] **Step 1: Write failing static connector contract tests**

Add `test_source_control_guides_github_login_scope_build_check_and_safe_update` to `test_web_static.py`. Parse `web/source-control.html` and assert accessible IDs for:

- `github-connect-panel`, `github-sign-in`, `github-login-status`, `github-login-cancel`, and device-code guidance;
- `repository-select`, `branch-select`, `connect-checkout`, and `connection-summary`;
- `check-build`, `update-build`, `build-status`, `local-build-details`, and `remote-build-details`;
- live regions and disabled initial states;
- calls to the new authentication/check/update routes;
- authenticated-login-scoped preference validation;
- branch-filtered commit loading using the selected branch;
- generic copy with no example repository name.

- [ ] **Step 2: Run the static test and verify RED**

Run: `python -m pytest test_web_static.py::WebStaticTests::test_source_control_guides_github_login_scope_build_check_and_safe_update -q`

Expected: FAIL because the progressive panel and branch selector do not exist.

- [ ] **Step 3: Implement the connection panel markup and styles**

Rework the top of `source-control.html` into the five progressive sections defined by the spec. Keep existing advanced sections below the panel. Add visible focus states, status colors that do not rely on color alone, responsive stacking, live regions, and explanatory text beside disabled controls.

- [ ] **Step 4: Implement authentication and selection state**

On signed-out status, offer explicit confirmed login, poll one session at a bounded interval, expose cancel and device-code guidance, then reload status/repositories on success. Populate the branch selector only after repository selection. Restore preferences only when the active login, repository list, and branch list validate them; otherwise clear dependent state.

- [ ] **Step 5: Implement checkout connection and build actions**

Connect only after local inspection matches the selected repository and branch. **Check build** sends a confirmed exact scope, renders all safe commit/status fields, and enables **Update to latest** only from the returned `update_allowed`. **Update to latest** confirms repository, branch, path, local SHA, and target SHA; submits the observed SHAs; then replaces the result with the returned post-update current status.

- [ ] **Step 6: Guard stale and mismatched UI state**

Changing login, repository, branch, or path clears the prior build result and disables update. Use a request generation token or abort controller so late responses from a previous selection cannot overwrite the current connection. Keep existing advanced controls synchronized with the selected repository/branch without silently switching the checkout.

- [ ] **Step 7: Run static and focused API tests and verify GREEN**

Run: `python -m pytest test_web_static.py test_web_api.py -k "github or source_control" -q`

Expected: PASS.

- [ ] **Step 8: Commit the guided connector UI**

```bash
git add web/source-control.html test_web_static.py
git commit -m "feat: add guided GitHub build connector"
```

### Task 6: End-to-end verification and documentation

**Files:**
- Modify: `README.md:88`
- Modify only if verification exposes a defect: files and corresponding tests from Tasks 1-5.

**Interfaces:**
- Consumes the completed connector.
- Produces documented setup and browser-verified behavior.

- [ ] **Step 1: Write the failing documentation assertion**

Extend the static connector test to require README guidance for browser/device login, repository and branch selection, build checking, fast-forward-only updates, and blocked dirty/diverged/mismatched states.

- [ ] **Step 2: Run the documentation assertion and verify RED**

Run: `python -m pytest test_web_static.py::WebStaticTests::test_source_control_guides_github_login_scope_build_check_and_safe_update -q`

Expected: FAIL because README describes only external `gh auth login`.

- [ ] **Step 3: Update user documentation**

Revise the GitHub integration section without naming an example repository. Explain that GitHub CLI owns credentials, the page prompts for login and selection, **Check build** fetches exact branch state, and **Update to latest** is explicit and fast-forward-only.

- [ ] **Step 4: Run focused automated verification**

Run: `python -m pytest test_github_auth.py test_github_cli.py test_web_api.py test_web_static.py -q`

Expected: PASS.

- [ ] **Step 5: Exercise the live page**

Run the application and verify in a browser at desktop and approximately 390px width:

- signed-out prompt, login start/device guidance/cancel, and successful account refresh;
- repository then branch selection with no hard-coded target;
- preference validation after reload and account change;
- matching checkout connection and build detail rendering;
- current, behind, dirty, mismatch, and stale-selection UI states;
- confirmed update of a disposable behind checkout and immediate current status;
- no page or console errors and no horizontal page scrolling.

- [ ] **Step 6: Run the complete repository suite**

Run: `python -m pytest -q`

Expected: All connector tests pass. Record every unrelated pre-existing failure or environment error by name.

- [ ] **Step 7: Inspect final repository hygiene**

Run: `git diff --check`

Expected: no whitespace errors.

Run: `git status --short`

Expected: only intended connector, test, documentation, spec, and plan changes remain.

- [ ] **Step 8: Commit documentation and verification fixes**

```bash
git add README.md docs/superpowers/specs/2026-11-21-github-connector-build-update-design.md docs/superpowers/plans/2026-11-21-github-connector-build-update.md
git commit -m "docs: describe GitHub build connector"
```
