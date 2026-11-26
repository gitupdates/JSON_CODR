# JSON_CODR

JSON_CODR V1.4.2 is a localhost-only, unified project agent for local Ollama models.

## Unified project workflow

Choose a model, describe the outcome in **Chat**, and run it. JSON_CODR creates one durable task for the conversation and routes all model, project, terminal, Git, browser, skill, and optional-provider work through that task. Users do not select an internal executor.

The response panel shows live activity and the requested and effective model identities. Use **Steer** by entering more direction while a task is active, **Stop** to request cancellation, **Retry** to create a linked retry, and **Undo** when the task produced a checkpoint. Execution details stay collapsed until needed. The **Live CLI** is the terminal view of the same local system, with command history, clipboard support, resize/reconnect, and the Ctrl+X then Ctrl+C interrupt chord.

V1.4.2 hardens direct CLI and browser coding workflows, adds immutable multi-action approval envelopes, improves live build identity and stable launcher recovery, upgrades development credential handling, and makes Ollama inference robust across reasoning-only, reset-prone, and thinking-incompatible models. V1.4.1 includes the staged self-update security release plus first-run bootstrap, administrator access, authenticated conversation persistence, live prompt CSRF fixes, approval visibility, and accurate failed-task reporting. Open **Settings → Verified updates** to inspect evidence, reconcile interrupted effects, quarantine candidates, and run explicitly authorized activation or rollback actions. V1.4.0 introduced staged self-update candidates, immutable proposal profiles, signed exact-tree verification and build manifests, strict expected-SHA publication leases, isolated health checks, real-browser checks, and stable activation and rollback supervision.

### Local identity

Open **Settings → Users & Access** to sign in and review server-derived roles. Development bootstrap can use a blank Administrator password only after a direct-loopback bypass is explicitly confirmed; the warning remains visible while it is active. Production bootstrap generates a temporary Administrator credential and requires a password change.

CLI lesson administration uses a separate 30-day `cli` credential encrypted with Windows DPAPI. Run `python -m web_app.core.cli auth login`, `auth status`, or `auth logout`. Revoking CLI credentials does not invalidate browser sessions. Account roles authorize identity and lesson administration, while the existing project-action approval boundary remains unchanged.

Local reads, searches, tests, bounded edits, and inference can run automatically inside the selected project boundary. Network access, installation, Git publication, destructive changes, and budget overrides require policy approval. Persistent grants remain project-scoped and can be revoked. A model without native tool calling may use a verified brokered route; JSON_CODR always displays the requested and effective model and never labels that route as native.

Attachments and folders can be selected or dropped into the page. Skills, MCP resources, browser automation, REA/Ghidra analysis, language intelligence, schedules, hooks, and child tasks use the same capability and policy path. Imported components are staged, probed, provenance-recorded, and either activated or quarantined. Optional provider failure leaves the base Ollama/CPU path available.

Remote PyPI and npm components require exact coordinates such as `cowsay==6.1` or `cowsay@1.6.0`. Before approval, BORG displays extracted identity, dependencies, hashes, entry points, blocked build behavior, and every required compatibility alteration. Installation preserves the acquired package, records observed native launchers separately from effective normalized commands, and activates only after a real probe succeeds. Local, Git, and archive sources cannot claim trusted registry provenance merely by including manifest filenames.

### Headless use

Submit through the neutral task API or CLI:

```powershell
python -m web_app.core.cli run --project D:\path\to\project --output text "Inspect, edit, and test this project"
```

`json`, `text`, and `stream-json` outputs are supported. Exit code `0` means completed, `1` means failed, and `2` means permission is required.

### Migrating beta data

The alpha migration is copy-on-write: the beta data root is hashed and never modified. General settings, project permissions, skills, benchmark history, imported resources, and valid conversations are copied; secrets are excluded. Older executor-specific configuration is archived as inactive evidence. Malformed records are reported, and the new destination can be rolled back without touching the source.

## Skill catalog and settings

Open **Skills** to see active installed and saved skills. Each skill can be selected for the current chat, edited, enabled or disabled, reviewed through **Details**, and exported as provider-neutral Markdown documentation. Saving an enabled skill also applies it to the active session and opens the refreshed active-skill list.

Selected skills are sent to every supported local LLM using the same JSON_CODR skill schema. The schema supplies identity, intent, required capabilities, syntax guidance, execution direction, and the complete converted instructions. Provider-specific tool names remain capability requirements and do not bypass local authorization.

New skills can target JSON_CODR directly without provider conversion. Follow the [JSON_CODR Skill Envelope Standard](docs/user/json-codr-skill-envelope.md); its logical fields are also published as a [JSON Schema](docs/user/json-codr-skill-envelope.schema.json). Both files are downloadable from the Skills panel.

Use **Scan folder** to inspect an explicit local directory for Claude, Codex, generic skill folders, ZIP archives, and 7z archives. Discovery is preview-only until **Install** is selected. If an explicit scan finds nothing, JSON_CODR offers a separately confirmed scan of known provider locations. It never scans whole drives or installs skills silently.

Open **Settings** to control whether the Skills panel reopens at startup and to rescan or remove approved skill directories. Settings are stored under the configured JSON_CODR data root and are shared across local sessions.

## Hardware optimization and benchmarks

Open **Settings → Hardware optimization** to detect CPU, supported GPU runtimes, and Windows NPU or AI accelerator devices. CPU is the compatibility fallback. An accelerated Ollama backend is saved only after an isolated model-generation probe succeeds; unavailable NPU runtimes are reported without being executed.

V1.0.10 introduces LocalPerf minimum conformance for repeatable local-inference measurements. Quick runs execute the versioned 12-prompt LocalPerf-Core-v1 workload three times and Thorough runs seven times after warmup. Each configuration records generation throughput, streaming time-to-first-token, peak VRAM, quality checks, configuration identity, and atomic aggregate JSON plus sample JSONL artifacts. Incomplete or failed configurations remain visible but cannot be selected as conforming winners. Ollama CPU remains the compatibility fallback.

V1.0.16 adds capability-first holistic rankings and portable benchmark baseline exports that preserve the underlying integrity and performance evidence. V1.0.15 added strict versioned Integrity & Comprehension evaluations plus integrity-only and equal-weight quality/performance leaderboard rankings sourced only from persisted local benchmark evidence.

V1.0.11 added sanitized-by-default portable `.localperf.zip` reference packages with checksums, schemas, methodology, reporting templates, preview/import validation, and explicit consent for system details. Hardware Optimization reports model-specific acceleration states and provides a pinned offline optimized-model catalog plus explicit on-demand search of approved remote model metadata. A model is labeled accelerated only after model-specific evidence or a successful provider probe.

The **Benchmarks** tab compares CPU with all detected runnable backends or one selected optimization using the same model and LocalPerf-Core-v1 workload. A selected accelerator is always paired with a fresh CPU baseline. **Quick** runs 12 prompts three times; **Thorough** runs them seven times after warmup. Results show conformance, model/runtime verification, TTFT, peak VRAM, duration, quality, token throughput, and CPU-relative performance. Benchmarking does not change the active backend, and canonical runs are stored under the JSON_CODR data root.

## Windows first run

From a clean, trusted Windows 11 x64 checkout, the supported setup path is:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\bootstrap.ps1
```

The bootstrap validates the checked-out commit and trusted `origin` remote before it changes the machine. It uses only allowlisted WinGet packages for Git, GitHub CLI, Python, and Ollama; creates an isolated JSON_CODR runtime under `%LOCALAPPDATA%\JSON_CODR`; asks before downloading the reviewed Ollama model; and securely prompts for a permanent, full Administrator password. On a machine with a healthy Intel NPU, it also installs the isolated Python 3.12/OpenVINO GenAI provider, downloads the pinned INT4 coding model into the machine-local cache, verifies its size and artifact checksums, and enables it only after OpenVINO exposes `NPU` and a bounded generation probe succeeds. It never installs or changes an NPU driver, and an optional NPU failure leaves Ollama/CPU available. That initial account and its browser/CLI credentials are visibly **non-production, non-expiring, and revocable**. Passwords and tokens are never put in command lines, receipts, or reports.

Useful modes:

```powershell
# Read-only diagnosis; changes nothing and never starts or stops a service.
.\bootstrap.ps1 -Check -NoGitHub

# Reconcile a prior bootstrap after a safe interruption.
.\bootstrap.ps1 -Repair

# Make the local web/CLI/Ollama path ready without GitHub authentication.
.\bootstrap.ps1 -NoGitHub

# Explicitly unverified local development source only; it cannot issue trusted readiness.
.\bootstrap.ps1 -DevelopmentSource -Check -NoGitHub
```

Bootstrap never kills or silently reuses a process on port 8765. A non-JSON_CODR listener is a conflict with an exact repair command. GitHub proof uses only `gh auth` and read-only `gh api user` / `git ls-remote`; it never pushes, creates repositories, or changes remotes. See [the first-run guide](docs/user/first-run.md) for repair and operational boundaries.

## Manual troubleshooting requirements

- Windows with Python 3.14 or newer
- Python 3.11 or 3.12 for the optional provider subprocess environments
- Ollama available in `PATH`
- At least one configured model installed in Ollama

Manual dependency installation is troubleshooting, not the first-run path. Install Python dependencies:

```powershell
py -3.14 -m pip install -r requirements.txt
```

The main host dependencies belong to Python 3.14+. Optional OpenVINO,
Ryzen AI, WinML, and DirectML provider packages are installed into isolated
Python 3.11/3.12 environments by JSON_CODR so their older binary compatibility
does not hold back the host runtime.

## Run the web interface

```powershell
.\run_web.ps1
```

The launcher starts Ollama when necessary, serves the application at
`http://127.0.0.1:8765`, and opens the page in your default browser. Press
Ctrl+C in the launcher window to stop the web server.

The launcher discovers both Python runtimes automatically. Set
`JSON_CODR_PYTHON` for the Python 3.14+ application runtime or
`JSON_CODR_COMPATIBLE_PYTHON` for the Python 3.11/3.12 provider runtime when
automatic discovery is not suitable.

If your Ollama models use a custom directory, set it before launching:

```powershell
$env:JSON_CODR_MODELS = 'D:\path\to\ollama-models'
.\run_web.ps1
```

The server binds only to `127.0.0.1`; it is not exposed to other machines.

## GitHub integration

Install the GitHub CLI (`gh`), then open **GitHub** in the web app. If the CLI
is signed out, the guided connection panel starts GitHub's browser/device
login and displays the one-time device code when needed. Credentials remain
in GitHub CLI's local credential store and are never handled by JSON_CODR.

After signing in, select an accessible repository and branch and connect its
local checkout. **Check build** fetches that exact branch and shows the local
and remote commits, timestamps, working-tree state, and ahead/behind counts.
When the checkout is clean, matches the selection, has no local-only commits,
and is strictly behind, **Update to latest** can perform a confirmed
fast-forward-only update. Dirty, detached, divergent, stale, or mismatched
checkouts are blocked without resetting, rebasing, switching, or discarding
work. Advanced issue, pull-request, release, branch, stage, commit, and push
controls remain available below the guided connection.

## Run tests

```powershell
python -m unittest discover -v
```
JSON_CODR
