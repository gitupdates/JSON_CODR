# JSON_CODR first run (Windows 11 x64)

Run the bootstrap from the repository root:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\bootstrap.ps1
```

It is designed to be safe to rerun. Normal mode accepts only a clean commit reachable from the configured `origin` remote. For an intentionally dirty, detached, extracted, or local-development tree, use `-DevelopmentSource`; its result is explicitly unverified and cannot serve as release/readiness evidence.

The only prerequisite installers are the reviewed WinGet package IDs declared in `config/bootstrap-prerequisites.json`. Bootstrap does not download or execute remote scripts, change host security settings, install global Python packages, or remove existing prerequisites. Python packages go into a runtime beneath `%LOCALAPPDATA%\JSON_CODR\runtime`.

If Windows reports a healthy Intel NPU, bootstrap conditionally provisions the release-owned OpenVINO path declared in `config/bootstrap-accelerators.json`. It installs the allowlisted Python 3.12 provider prerequisite, creates an isolated provider environment, requires OpenVINO to enumerate `NPU`, downloads the exact pinned `OpenVINO/Qwen2.5-Coder-1.5B-Instruct-int4-ov` revision, checks the byte bound and reviewed artifact SHA-256 values, and runs a bounded generation probe before persisting verification. No NPU driver is installed or modified. A missing or incompatible NPU is recorded as skipped/unavailable and cannot prevent the base Ollama/CPU path from starting.

The first interactive run may ask for three things: confirmation to pull the reviewed Ollama model, a permanent full Administrator password, and GitHub CLI sign-in. The Administrator, browser sessions, and CLI credentials use the initial **non-production, non-expiring, revocable** policy. Secrets stay in the owning stores and are not included in a receipt, report, or command line.

## Safe modes

```powershell
# Read-only inspection; makes no changes.
.\bootstrap.ps1 -Check -NoGitHub

# Retry/reconcile bootstrap-owned incomplete state.
.\bootstrap.ps1 -Repair

# Explicitly complete only local web/CLI/Ollama readiness.
.\bootstrap.ps1 -NoGitHub

# Verify prerequisites without starting the service.
.\bootstrap.ps1 -NoStart
```

`-NoStart` reports `ACTION REQUIRED`, never `READY`. `-Check` reports an Intel NPU only as a read-only candidate and does not install its runtime or model. `-NoGitHub` is the only path that can report `READY (LOCAL ONLY)`. Without it, GitHub must be authenticated through the official `gh` flow, then verified with read-only account and remote checks. Bootstrap does not choose among multiple identities/remotes silently and never pushes, mutates a remote, or creates a repository.

## Operations and repair

Use `-Check` before repair if something is unexpected. If port 8765 already has a listener, bootstrap proves it is JSON_CODR before reuse; otherwise it stops and never kills it. Do not delete `%LOCALAPPDATA%\JSON_CODR` to repair an installation: it may contain user data and credentials. Bootstrap preserves existing accounts, data roots, active launcher state, Git state, and unrelated processes.

The normal summary includes the exact repair command. `-Json` writes one versioned result document to stdout; human diagnostics go to stderr. Statuses are `READY`, `READY (LOCAL ONLY)`, `ACTION REQUIRED`, or `BLOCKED`.
