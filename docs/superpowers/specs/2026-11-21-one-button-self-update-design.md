# One-button self-update design

## Intent

Let a configured JSON_CODR installation check its selected GitHub repository and branch, show the installed and available commits, and pull a safe update from one primary action. The action must never overwrite local work or silently change repository, branch, account, host, or target commit.

## Behavior

- Rename the primary build action to **Check for updates**.
- Use the already saved and visibly selected GitHub repository, branch, and local checkout; first-time users still sign in and select this scope.
- On click, run the existing authenticated build comparison and render local/remote commit details.
- If the checkout is current, ahead, diverged, dirty, detached, mismatched, or otherwise unsafe, stop after showing the reason.
- If it is strictly behind and the existing guarded update contract allows a fast-forward, ask the user to confirm the exact repository, branch, checkout, current commit, and target commit.
- After confirmation, call the guarded update endpoint with the checked SHAs and authenticated identity. Revalidation and an immutable-SHA fast-forward remain mandatory.
- If confirmation is declined, keep the checked build result visible and leave the checkout unchanged.
- On success, render the refreshed current-build details. On conflict, clear the stale snapshot and require a new check.

## Approaches considered

1. **One check action followed by conditional confirmation and update — selected.** This matches the requested workflow while retaining the connector's safety boundary.
2. Keep separate **Check build** and **Update to latest** buttons. Safest visually, but does not provide the requested one-button workflow.
3. Automatically update immediately after checking. Rejected because a pull is a local mutation and the user explicitly requested confirmation.

## Constraints and non-goals

- Only fast-forward updates are supported; no reset, checkout, rebase, merge commit, force operation, dependency installation, restart, or automatic branch switching.
- This change does not hard-code JSON_CODR or any example repository. The selected connector scope remains generic.
- Updating files does not automatically restart a running server; the UI reports the checked-out source state truthfully.

## Verification

- Static UI tests cover the combined label and conditional confirmed-update path.
- API/CLI safety tests remain green, including identity binding, stale snapshot rejection, clean-tree enforcement, and exact-SHA fast-forwarding.
- Live verification covers current/ahead behavior without mutating the repository and confirms the button remains available for a subsequent check.
