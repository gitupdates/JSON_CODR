# GitHub Connector Build Update Design

## Intent

Turn the existing Source Control page into a repository-agnostic GitHub connector that guides a user from authentication through repository and branch selection to a clear local-versus-remote build check. When the connected local checkout is safely behind the selected GitHub branch, the user can explicitly request a fast-forward update from the same connection panel.

The connector must work for repositories available to the authenticated user. The repository shown in the supplied screenshot is an example only and must never be embedded as a default or special case.

## Goals

- Prompt an unauthenticated user to sign in through the GitHub CLI browser/device flow.
- Keep authentication credentials in GitHub CLI's local credential store; JSON_CODR must not receive or persist tokens.
- Require an authenticated user to select an accessible repository and one of its branches.
- Connect the selected remote scope to an explicitly inspected local Git checkout.
- Provide a single **Check build** action that fetches remote state and reports local and remote commit details.
- Report repository and branch match, local HEAD, remote tip, ahead/behind counts, working-tree state, last-check time, and a plain-language status.
- Enable **Update to latest** only when a confirmed fast-forward update is safe.
- Refresh the connection details after an update so success is visible immediately.
- Preserve the existing advanced GitHub and local source-control operations below the guided connection panel.

## Non-goals

- Hard-code, recommend, or silently connect to any specific repository or branch.
- Store GitHub passwords, personal access tokens, OAuth tokens, or GitHub CLI credential files.
- Automatically update without a user clicking the update button and approving the confirmation.
- Reset, rebase, force-pull, force-push, discard local changes, resolve divergence, or switch branches automatically.
- Treat a release tag, package version, or application version as the authoritative build comparison. The selected branch tip is authoritative.
- Replace the existing GitHub CLI and FastAPI architecture.
- Support GitHub Enterprise hosts or switch among multiple GitHub CLI accounts. This version uses the active `github.com` CLI identity only.

## User flow

1. The Source Control page checks GitHub CLI availability and authentication.
2. If signed out, the connection panel shows **Sign in to GitHub** and explains that a browser/device flow will open. Starting sign-in is an explicit action.
3. The backend starts one bounded `gh auth login --web --hostname github.com` session. The page polls its sanitized status and then reloads account and repository data when authentication succeeds. Duplicate login attempts are rejected while a session is active. If a browser cannot be opened, the panel shows the temporary one-time code and canonical GitHub verification URL for that active session only.
4. After login, the page loads only repositories visible to that GitHub CLI identity. The user selects a repository and then a branch.
5. A remembered repository or branch may be restored only when it is still present in the newly authenticated account's results. Otherwise the selectors return to an explicit unselected state.
6. The user enters or chooses a local checkout path and clicks **Connect checkout**. The connector inspects it without changing it.
7. The panel compares the checkout's GitHub origin and current branch with the selected repository and branch. Mismatches are clearly reported and block updates.
8. **Check build** performs an authenticated fetch of the inspected checkout's origin, then calculates its relationship to the selected branch.
9. The connection panel shows one of: current, behind, ahead, diverged, local changes, repository mismatch, branch mismatch, detached HEAD, no upstream, unavailable, or error.
10. When status is behind with a clean worktree, matching repository/branch, and no local-only commits, **Update to latest** becomes available.
11. Updating requires browser confirmation naming the repository, branch, local path, current commit, and target commit. The backend repeats all safety checks and runs a fast-forward-only update.
12. The page immediately rechecks and displays the new current state.

## Selected approach

### Unified connection panel

Add a guided connection panel at the top of the existing Source Control page. It owns authentication status, remote repository/branch selection, local checkout connection, build comparison, and safe update actions. Existing advanced repository, collaboration, release, and local Git controls remain available below it and reuse the selected scope where appropriate.

This approach was selected because it provides a direct everyday workflow without removing the existing advanced tools or introducing a second GitHub integration architecture.

## Alternatives considered

### Separate setup wizard

A multi-screen wizard would be friendly on first use but would make routine repository or branch switching slower and require a larger navigation redesign.

### Application-managed remote clone

The application could always clone the selection into a managed directory. That would simplify local mapping but could duplicate existing worktrees and obscure which copy is being updated.

## Connection state and persistence

The browser keeps a small, non-secret connection preference containing the authenticated login name, selected repository full name, selected branch name, and local checkout path. On every page load:

- authentication is checked before preferences are applied;
- a stored repository is accepted only if returned for the current login;
- a stored branch is accepted only if returned for that repository;
- a stored checkout is inspected again before it is considered connected;
- changing account or repository clears dependent branch and comparison state;
- changing branch clears the previous comparison and disables updating until a new check completes.

No server-side connector session survives an application restart except the authentication state already maintained by GitHub CLI.

## Build comparison model

For this connector, a **build** is the exact Git commit checked out locally compared with the tip of the selected remote branch after a successful fetch.

The check result contains only display-safe metadata:

- selected `owner/repository` and branch;
- normalized local GitHub origin identity;
- local branch and upstream name;
- local HEAD SHA, short SHA, subject, author name, and authored timestamp;
- remote branch SHA, short SHA, subject, author name, and authored timestamp;
- ahead and behind counts from the merge-base relationship;
- clean/dirty working-tree state;
- checked-at timestamp;
- machine-readable status and plain-language detail;
- whether update is allowed and, when blocked, the exact reason.

The comparison must use Git argument arrays, validated repository/branch values, and locally fetched refs. No user-supplied value is interpolated into a shell command.

The explicitly selected repository and branch are authoritative for comparison. A missing configured upstream is reported as informational detail but does not block a check or safe update when the local origin and current branch match the selection. The update does not silently create or change upstream configuration.

## Safe update rules

**Update to latest** is enabled only when all of the following remain true:

- GitHub CLI is authenticated;
- a repository and branch are selected;
- the local origin resolves to the selected GitHub repository;
- the current local branch exactly matches the selected branch;
- the worktree and index are clean;
- HEAD is attached;
- the selected remote branch exists after fetch;
- local ahead count is zero;
- remote behind count is greater than zero;
- the last comparison belongs to the same repository, branch, path, local HEAD, and remote SHA.

The update endpoint must fetch and recompute these facts rather than trusting browser state. It then runs `git merge --ff-only` against the exact validated remote-tracking ref. Any state change, divergence, local modification, missing ref, mismatch, or Git failure aborts without resetting or cleaning the checkout.

## Authentication design

- `GET /api/github/status` remains the authoritative signed-in check.
- Authentication and repository reads target `github.com` and its currently active GitHub CLI account. Other hosts and inactive accounts are not enumerated or switched by this connector.
- `POST /api/github/auth/login` starts a GitHub CLI browser login only after request confirmation.
- `GET /api/github/auth/login/{session_id}` reports `starting`, `waiting`, `authenticated`, `failed`, `cancelled`, or `expired` plus sanitized user-facing detail. While waiting, it may return the parsed one-time device code and the fixed `https://github.com/login/device` URL. The code is kept only in the in-memory session, is never logged or persisted, and disappears with the session.
- `POST /api/github/auth/login/{session_id}/cancel` stops only that active login process.
- Only one active login session is allowed per application instance.
- Login sessions have a fixed timeout and are removed after a short terminal-state retention period.
- Command output is redacted before it can reach logs or the browser. Environment variables and credential-store contents are never returned.
- If GitHub CLI is missing, the UI explains that prerequisite and does not offer a broken login action.

## API changes

Add narrowly scoped request and response contracts:

- authentication session start, status, and cancellation;
- `POST /api/github/local/check-build` with confirmed local path, selected repository, and selected branch;
- `POST /api/github/local/update-build` with the same scope plus the local and remote SHAs observed by the last check and `confirmed: true`.

Both build endpoints operate on the selected local checkout. The check endpoint is state-changing at the Git level because it fetches, so it retains browser confirmation and request-level confirmation. The update endpoint repeats validation and never accepts an arbitrary remote or refspec.

## Interface design

The connection panel is ordered and progressive:

1. **GitHub account** — signed-out prompt or signed-in identity with refresh.
2. **Remote scope** — repository selector followed by branch selector.
3. **Local checkout** — path, inspect/connect action, and match summary.
4. **Build status** — current status banner plus local and remote detail cards.
5. **Actions** — **Check build** and conditionally enabled **Update to latest**.

Controls that depend on an earlier step remain disabled with nearby explanatory text. Loading, success, blocked, and failure states use live regions and do not reuse stale results. The interface remains keyboard accessible and responsive at narrow widths.

## Errors and recovery

- Authentication failure leaves the user signed out and offers a retry.
- Closing or denying the browser flow produces a clear cancelled/failed state.
- Repository or branch deletion clears the invalid selection on refresh.
- Network or GitHub failure preserves the selection but marks the check unavailable; it never labels stale data current.
- Fetch or update failure shows sanitized Git output and leaves the checkout untouched except for fetched remote refs.
- A stale update request returns a conflict-style response and instructs the user to check again.

## Security and permission boundaries

- GitHub CLI remains the sole credential owner.
- Existing `X-JSON-CODR` request gating remains required.
- Login, fetch/check, cancel, and update operations require explicit request models and validation.
- The update action requires both browser confirmation and `confirmed: true` at the API.
- Local paths must pass the existing repository-root validation and GitHub-origin checks.
- Repository and branch values are validated independently and URL-encoded where used in HTTP routes.
- Subprocesses run without a shell and with bounded timeouts.
- Returned error text is redacted for tokens, credentials, and sensitive paths where applicable.

## Verification

- Unit-test authentication session lifecycle, duplicate prevention, timeout/cancellation, missing CLI behavior, and output redaction.
- Unit-test build comparison for current, behind, ahead, diverged, dirty, detached, missing-upstream, repository mismatch, branch mismatch, and missing-remote-ref states.
- Unit-test update revalidation, stale SHA rejection, fast-forward-only invocation, and refusal of every blocked state.
- API-test request confirmation, authentication/session routes, scope forwarding, error mapping, and safe response fields.
- Static/UI-test progressive controls, accessible labels/live regions, generic copy, selection invalidation, build details, and guarded update behavior.
- Exercise the live page through signed-out, sign-in, repository/branch selection, matching checkout, behind checkout, update, and post-update current states.
- Run focused GitHub and static-page tests, then the complete repository suite and a final diff/whitespace check.
