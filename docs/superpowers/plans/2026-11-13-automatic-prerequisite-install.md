# Automatic Prerequisite Installation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Detect missing validated Python and Node dependencies and automatically install only those dependencies through the visible live CLI.

**Architecture:** `DependencyService` will delegate installed-version checks to a focused preflight component and return only missing or incompatible packages as automatic suggestions. A small browser-safe queue will deduplicate commands and feed them into the existing terminal WebSocket so PowerShell streams package-manager output through the current CLI panel.

**Tech Stack:** Python 3.13, FastAPI, `importlib.metadata`, `packaging`, npm CLI, browser JavaScript, WebSocket terminal.

**Spec:** `docs/superpowers/specs/2026-11-13-automatic-prerequisite-install-design.md`

## Global Constraints

- Accept dependencies only from validated `requirements.txt`, `requirements-dev.txt`, and `package.json` entries.
- Never use `shell=True` for preflight checks.
- Do not install OS packages, drivers, services, or administrator-level components.
- Cap each generated command at 100 packages.
- Do not automatically retry a failed command in the same page session.
- Keep terminal output visible and preserve the existing Stop control.

## Review Focus

- A malformed or shell-like package entry must never reach preflight or terminal execution; Task 1 keeps the existing rejection tests and adds mixed valid/invalid coverage.
- An installed package with an incompatible version must be treated as missing; Task 1 tests Python specifier and npm range failures.
- A missing `npm` executable or timed-out preflight must produce a visible install attempt, not crash dependency detection; Task 1 tests preflight failure fallback.
- Repeated dependency refreshes during one page session must dispatch a command once; Task 2 tests queue deduplication behavior.
- Multiple distinct automatic commands must retain order and remain stoppable through the existing terminal; Task 2 tests ordered dispatch and browser integration.

---

### Task 0: Windows-native SDD workspace helper

**Files:**
- Create: `scripts/sdd-workspace.ps1`
- Create: `test_sdd_workspace.py`

**Interfaces:**
- Consumes: one plan file path while running inside a Git working tree.
- Produces: `.superpowers/sdd/<plan-name>/` with a `plan-path` ownership marker and prints its absolute path.

- [x] **Step 1: Write failing PowerShell helper tests**

Test normal plan-scoped resolution, repo-relative ownership markers, the scratch `.gitignore`, stable repeat resolution, and disambiguation for colliding plan basenames.

- [x] **Step 2: Run the tests and verify RED**

Run: `python -m unittest -v test_sdd_workspace`
Expected: FAIL because `scripts/sdd-workspace.ps1` does not exist.

- [x] **Step 3: Implement the PowerShell helper**

Use only PowerShell and Git primitives; preserve the bundled helper's ownership and collision behavior without Bash or Unix coreutils.

- [x] **Step 4: Run Task 0 tests and commit**

Run: `python -m unittest -v test_sdd_workspace`
Expected: PASS.

Commit: `git commit -m "Add Windows SDD workspace helper"`

---

### Task 1: Missing-dependency preflight

**Files:**
- Modify: `web_app/dependencies.py`
- Modify: `test_dependencies.py`

**Interfaces:**
- Produces: `DependencyPreflight.missing_python(specs: list[str]) -> list[str]`
- Produces: `DependencyPreflight.missing_node(packages: list[str], cwd: Path) -> list[str]`
- Produces: `DependencyService(..., preflight: DependencyPreflight | None = None, install_root: Path | None = None)`
- Produces: automatic `DependencySuggestion` values containing only missing or incompatible packages.

- [ ] **Step 1: Write failing Python preflight tests**

Add tests proving a satisfied PEP 440 requirement is omitted, an absent or incompatible requirement is returned, invalid manifest lines remain rejected, and metadata lookup failures fall back to missing.

- [ ] **Step 2: Run the Python tests and verify RED**

Run: `python -m unittest -v test_dependencies.DependencyServiceTests`
Expected: FAIL because preflight interfaces and automatic missing-only suggestions do not exist.

- [ ] **Step 3: Implement Python preflight**

Use `packaging.requirements.Requirement`, canonical distribution lookup, marker evaluation, and `importlib.metadata.version`. Preserve original validated spec strings in generated commands.

- [ ] **Step 4: Write failing Node preflight tests**

Add tests for satisfied and incompatible `package@range` values, scoped packages, missing npm, timeout, and argument-array invocation with `shell=False`.

- [ ] **Step 5: Run the Node tests and verify RED**

Run: `python -m unittest -v test_dependencies.DependencyServiceTests`
Expected: FAIL because Node preflight is not implemented.

- [ ] **Step 6: Implement Node preflight and missing-only suggestions**

Run bounded `npm ls <package@range> --depth=0 --json` checks from the install root. Return failed, missing, incompatible, or uncheckable entries so npm reports the authoritative result in the live CLI. Set `automatic=True`; return no suggestion when every dependency is satisfied.

- [ ] **Step 7: Run Task 1 tests and commit**

Run: `python -m unittest -v test_dependencies`
Expected: PASS.

Commit: `git commit -m "Add dependency preflight checks"`

### Task 2: Automatic live CLI dispatch

**Files:**
- Create: `web/dependency_install_queue.js`
- Create: `test_dependency_install_queue.py`
- Modify: `web/index.html`
- Modify: `web/app.js`
- Modify: `test_web_static.py`

**Interfaces:**
- Consumes: Task 1 automatic suggestions with `command` and `automatic`.
- Produces: `createDependencyInstallQueue(runCommand)` with `enqueue(command) -> boolean`.
- Produces: `runTerminalCommand(command?: string) -> Promise<void>` for manual and automatic execution.

- [ ] **Step 1: Write failing queue behavior tests**

Use Node from `test_dependency_install_queue.py` to prove duplicate commands dispatch once, distinct commands dispatch in input order, and a rejected command does not poison later queue entries.

- [ ] **Step 2: Run the queue tests and verify RED**

Run: `python -m unittest -v test_dependency_install_queue`
Expected: FAIL because `web/dependency_install_queue.js` does not exist.

- [ ] **Step 3: Implement the queue module**

Export through CommonJS for Node tests and `window.createDependencyInstallQueue` for the browser. Mark a command seen before running it; keep a caught tail promise so later commands continue after failure.

- [ ] **Step 4: Write failing browser contract tests**

Assert the queue script loads before `app.js`, automatic suggestions are enqueued, the terminal panel opens, and the exact suggestion command reaches `runTerminalCommand(command)`.

- [ ] **Step 5: Run browser tests and verify RED**

Run: `python -m unittest -v test_web_static`
Expected: FAIL because the app does not consume automatic suggestions.

- [ ] **Step 6: Integrate automatic dispatch**

Load the queue module before `app.js`; adapt `runTerminalCommand` to accept an optional command; enqueue each automatic suggestion after rendering; open the terminal panel, show an `Installing prerequisites` status, send the validated command, and leave failures visible without retry.

- [ ] **Step 7: Run Task 2 tests and commit**

Run: `python -m unittest -v test_dependency_install_queue test_web_static`
Expected: PASS.

Commit: `git commit -m "Auto-install missing prerequisites in live CLI"`

### Task 3: End-to-end verification and publication

**Files:**
- Modify: `docs/superpowers/plans/2026-11-13-automatic-prerequisite-install.md` (mark completed steps)

**Interfaces:**
- Consumes: Task 1 preflight and Task 2 automatic dispatch.
- Produces: verified running application and updated PR branch.

- [ ] **Step 1: Run full automated verification**

Run: `python -m unittest discover -v`, `node --check web/app.js`, and `git diff --check`.
Expected: all tests pass; only documented environment-dependent skips remain.

- [ ] **Step 2: Run a controlled browser scenario**

Import a harmless manifest with one already-satisfied package and one bounded missing test package or use a controlled fixture response; verify only the missing command is sent once, terminal output is visible, and Stop remains enabled. Do not leave test packages installed in the production environment.

- [ ] **Step 3: Review and publish**

Request a final read-only review, address actionable findings, push `codex/theme-settings`, and update PR #2 with verification results.
