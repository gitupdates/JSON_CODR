# Source Control Active Scope Design

## Intent

Make the local Source Control page safer and easier to use by giving every GitHub and Git action an explicit repository-and-branch scope. A user should always know which repository and branch an action will read, modify, synchronize, or version.

## Goals

- Add a prominent, persistent Active Scope area with repository and branch selectors.
- Preserve the selected repository and branch across refreshes when they still exist.
- Filter remote commit history to the selected branch.
- Default branch-sensitive pull-request and release fields from the active branch.
- Compare the inspected local checkout with the remote scope and clearly warn about repository or branch mismatches before synchronization.
- Improve hierarchy, responsiveness, accessibility, loading feedback, and error messages.
- Repair broken character encoding such as `Â·`.
- Preserve confirmation gates for every write operation.

## Non-goals

- Automatically switch a local checkout to the selected remote branch.
- Run unattended commits, pulls, pushes, merges, or releases.
- Change GitHub authentication, credential storage, or permission boundaries.
- Replace the existing FastAPI and GitHub CLI architecture.

## Constraints and safety

- The page remains a local, buildless HTML/CSS/JavaScript interface served by the existing FastAPI application.
- Repository and branch values must continue to be validated and URL-encoded at API boundaries.
- Destructive and remote write operations retain browser and request-level confirmation.
- A local/remote mismatch must be visible before sync actions and must not silently retarget the local checkout.

## Approaches considered

1. **Persistent Active Scope — selected.** One repository-and-branch scope drives remote data and supplies safe defaults. Local state remains separately inspected but is compared against this scope. This gives the clearest target without removing advanced controls.
2. **Independent remote and local selectors.** More flexible, but makes accidental cross-repository or cross-branch actions easier.
3. **Guided step-by-step workflow.** Safest for new users, but a larger redesign that slows repeated expert use.

## Interaction design

- Place a visually distinct Active Scope panel immediately after account status.
- Repository selection loads branch choices; branch selection refreshes branch-specific data.
- Show repository visibility, selected branch, default/protected status, and current local-match state as concise status chips/cards.
- Organize the page into Remote activity, Collaboration, Releases, and Local sync sections; keep repository administration collapsed.
- Disable branch-dependent actions until a branch is selected and explain why.
- When a local checkout is inspected, compare its GitHub repository and current branch with Active Scope. Display matched, repository mismatch, or branch mismatch states next to sync controls.
- Keep sync actions scoped to the inspected local checkout, but name the exact repository and branch in confirmations.

## API and data changes

- Extend remote commit listing with an optional validated branch parameter and forward it to GitHub's commits API as `sha`.
- Reuse the existing branches API for selector population.
- No new credentials, persistent server state, or destructive endpoints are introduced.

## Verification

- Add or update unit tests for branch-filtered commits and API forwarding.
- Add static/UI assertions for the repository and branch scope controls and repaired text.
- Run targeted GitHub CLI, web API, and static page tests.
- Exercise the live page in a browser at desktop and narrow viewport widths, including repository selection, branch selection, mismatch messaging, and disabled/loading states.

