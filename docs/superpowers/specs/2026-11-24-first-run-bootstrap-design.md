# First-Run Bootstrap Design

## Intent

Make JSON_CODR usable without Codex on a fresh supported Windows machine through one explicit command. The command installs trusted prerequisites, configures an isolated application environment, starts JSON_CODR, and proves that the web interface, native CLI, local inference, and GitHub integration are ready—or stops with an exact, recoverable diagnosis.

The primary operator is a person who has cloned or downloaded JSON_CODR but should not need to understand Python environments, ports, Ollama service management, GitHub CLI credential storage, or JSON_CODR's internal launcher.

## Goals

- Provide one documented PowerShell entry point for first-run setup and repair.
- Install only allow-listed prerequisites from pinned, authenticated sources.
- Be idempotent and safe to rerun after success, cancellation, restart, or partial failure.
- Align the launcher, CLI, health probes, documentation, and displayed version around one canonical configuration.
- Finish with real end-to-end proofs rather than successful-install assumptions.
- Preserve credentials in their owning systems: GitHub credentials in `gh`, JSON_CODR CLI credentials in its protected credential store, and no secrets in logs.
- Leave a concise machine-readable receipt and a human-readable diagnostic report.
- Operate independently of Codex, Codex skills, or Codex-specific directories.

## Non-goals

- Supporting Linux or macOS in this first release.
- Installing GPU/NPU-specific optional providers during the base bootstrap.
- Automatically granting GitHub repository write access or publishing changes.
- Automatically installing arbitrary models, packages, skills, or plugins from user-provided locations.
- Replacing the existing application launcher or security policy with installer-only authority.
- Building MSI/MSIX packaging in this phase.
- Claiming a first-run guarantee for Windows 10, Windows on ARM, Linux, or macOS.

## Supported Host and Source

The initial guaranteed host is Windows 11 x64 running inbox Windows PowerShell 5.1. PowerShell 7 is neither required nor installed. Other hosts fail the support gate with a diagnostic; they are not silently treated as verified.

Normal bootstrap requires a clean Git checkout at a commit reachable from a configured trusted remote. The receipt binds the normalized remote, commit object, commit tree, and bootstrap-manifest digest. Dirty worktrees, repositories without a trusted remote, and source folders without Git metadata stop before installation.

An explicit `-DevelopmentSource` mode permits dirty, local-only, detached, or extracted source for development. It is visibly unverified, cannot issue a readiness or release receipt, cannot enable verified self-update, and records the exact local tree evidence available.

## Anti-goals

The bootstrap must not:

- pipe remote scripts directly into PowerShell;
- download mutable `latest` artifacts without identity and integrity validation;
- weaken execution policy, antivirus, firewall, UAC, TLS validation, or certificate checks;
- log passwords, tokens, device codes, cookies, authorization headers, or credential files;
- silently reuse a conflicting service, port, repository, data root, or GitHub identity;
- report readiness while any mandatory smoke test is skipped;
- delete user data, reset Git state, discard work, or modify GitHub repositories;
- depend on Codex being installed or authenticated.

## Selected Approach

Use a transactional PowerShell bootstrap as the canonical first-run and repair engine. It builds on the repository's Windows and PowerShell architecture and can later be invoked by a packaged installer.

Two alternatives were considered:

1. A packaged MSI/MSIX offers a smoother shell experience but introduces signing, packaging, upgrade, and release infrastructure before the underlying setup path is reliable.
2. A container-first installation improves reproducibility but complicates local Ollama acceleration, Windows path permissions, browser authentication, and hardware-provider access.

The transactional PowerShell approach is selected because it minimizes new platform machinery while supporting strong validation and recovery.

## User Experience

The README presents one command from the repository root:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\bootstrap.ps1
```

`-ExecutionPolicy Bypass` applies only to that process and is not written to machine policy. The script displays its own repository path, source revision, planned installations, and whether elevation is required before it changes the machine.

The default run performs these phases:

1. validate the repository and host;
2. acquire an inter-process bootstrap lock;
3. inspect installed prerequisites and select exact versions;
4. request elevation once if machine-level installation is required;
5. install or repair missing prerequisites;
6. create or repair an isolated JSON_CODR Python environment;
7. configure canonical ports, roots, and launcher settings;
8. initialize the local application identity safely;
9. start or locate the supervised server;
10. prove web, CLI, Ollama, and GitHub readiness;
11. write receipts and print the exact next command.

Supported modes:

- default: install, configure, start, and verify;
- `-Check`: read-only diagnosis with no installation or configuration changes;
- `-Repair`: reconcile an existing installation and rerun all proofs;
- `-NoGitHub`: make GitHub explicitly optional while still proving local operation;
- `-NoStart`: install and verify static prerequisites without leaving the server running;
- `-Json`: emit a stable machine-readable result in addition to the human summary.
- `-DevelopmentSource`: permit an explicitly unverified local source tree without issuing trusted readiness evidence.

In `-Json` mode, stdout contains only one versioned JSON result document. Progress, prompts, and human diagnostics use stderr. When stdin is noninteractive, any required confirmation or authentication returns `ACTION REQUIRED` with a stable resume command; the bootstrap never guesses consent.

## Trust and Supply-Chain Policy

Every installable prerequisite is declared in a repository-owned manifest containing:

- logical component ID;
- acceptable Windows architectures;
- exact version or bounded compatible version;
- trusted publisher identity;
- trusted acquisition mechanism;
- expected package identifier;
- integrity evidence required after installation;
- executable path and version probe;
- whether elevation is required.

Initial allowlist:

- Git for Windows from the official `winget` package;
- GitHub CLI from the official `winget` package;
- supported CPython runtimes from official Python Software Foundation packages;
- Ollama for Windows from its official package;
- Python packages from `requirements.txt` installed into a repository-independent virtual environment using hashes from a generated lock file.

The bootstrap refreshes `winget` source metadata only through normal `winget` behavior and verifies returned package ID, version, and publisher before accepting a component. If `winget` itself is unavailable, corrupt, or cannot establish publisher trust, bootstrap stops with a remediation report; it does not fall back to arbitrary web downloads.

The prerequisite manifest pins the exact `winget` source and package identifiers, accepted versions, architectures, publishers, installer scopes, agreement flags, and noninteractive flags. Planning fails if installed `winget` cannot expose enough evidence to validate a declared trust condition. Resolved executable paths are reprobed directly after installation; bootstrap never depends on the parent process receiving a refreshed `PATH`.

Python dependencies require a committed, hash-locked dependency file generated from the reviewed requirements. Installation uses `--require-hashes`, disables interactive prompts, and never installs into the global interpreter.

## Privilege Model

The unelevated process performs inspection, owns the user-facing transcript, and computes the installation plan. If required, it writes a non-secret, canonical plan to the bootstrap state directory and launches one elevated child with a random one-time receipt nonce. The elevated child may execute only manifest-listed machine installation steps. It cannot initialize accounts, access application credentials, authenticate GitHub, start autonomous updates, or modify the repository.

The parent validates the elevated child's signed/nonce-bound result and independently reprobes every installed executable. User-scoped installation is preferred when the official package supports it. Bootstrap never runs the full application as Administrator.

The elevation plan and result live in a user-owned directory whose Windows ACL is restricted to the initiating user and Administrators. The parent writes the canonical plan atomically with a cryptographically random nonce and digest. The elevated child accepts only that exact manifest-bounded plan, writes an atomic nonce/digest-bound result, and removes no prerequisite. “Signed” in this design means this protected ACL plus nonce-and-digest binding; no unsupported public-key claim is made.

## Transaction and Recovery Model

Bootstrap stores state under `%LOCALAPPDATA%\JSON_CODR\bootstrap`, outside the repository. A single OS-visible lock prevents concurrent runs. Each run has an immutable ID and append-only phase journal containing sanitized inputs, state transitions, command exit classifications, and verification results.

Each phase is one of `pending`, `running`, `verified`, `failed`, or `recovery-required`. On restart, the script never trusts `running`; it reprobes the external state and deterministically marks the phase verified, retries it, or stops with a conflict.

The lock records PID, process-start identity, run ID, and heartbeat. Stale recovery requires proving that the exact owner process is dead. Journal records use write-through temporary files, file flush, atomic replacement, and directory durability where Windows permits it. A required reboot is recorded as `ACTION REQUIRED`; bootstrap prints an explicit resume command and never schedules itself automatically.

No rollback removes a prerequisite that existed before bootstrap. Artifacts created by the current run are recorded explicitly. Repair may replace an incomplete virtual environment through atomic directory promotion, while the previous verified environment remains available until the new one passes import and application probes.

Existing data roots, accounts, credential stores, launcher pointers, and verified environments are discovered and reconciled. Bootstrap never overwrites an existing account or active-build pointer. `-Repair` reuses valid state, quarantines only bootstrap-owned incomplete artifacts, and stops on conflicting ownership or identity evidence.

## Canonical Configuration

A single repository module or data document owns:

- application version;
- server host and port;
- health and task API paths;
- supported host Python range;
- compatible-provider Python range;
- default data and launcher roots.

The canonical artifact is a versioned, machine-readable repository file consumed by both Python and PowerShell. Environment overrides are explicit runtime inputs validated against its schema and included in the receipt; they never create hidden alternate defaults. The implementation plan will choose the path and schema before changing consumers.

PowerShell, Python CLI, launcher, health response, tests, and README verification consume or validate this canonical source. The CLI must not carry an independent default port.

The canonical server remains loopback-only. If the configured port is occupied, bootstrap identifies the owning process. It may reuse it only when a challenge-bound JSON_CODR health response proves the expected installation and revision. Otherwise it stops and reports the conflict; it never kills an unrelated process or silently selects a new port.

The health challenge contains a caller nonce, installation ID, active revision, active tree, configuration digest, process-start time, and response timestamp authenticated by the local installation identity. Reuse requires freshness and exact agreement with the bootstrap receipt.

## Python Environment

The host application runs from `%LOCALAPPDATA%\JSON_CODR\runtime\<environment-id>` rather than the repository's or user's global site-packages. The environment ID binds the Python implementation, Python version, dependency-lock digest, architecture, and application compatibility version.

Bootstrap verifies:

- interpreter publisher, path, architecture, and version;
- virtual-environment isolation;
- every locked dependency and hash;
- import of mandatory runtime modules;
- absence of dependency resolution drift;
- launch through the exact interpreter recorded in the receipt.

Optional Python 3.11/3.12 provider environments are not mandatory for the base local path. Their absence is reported as an optional capability limitation rather than making first run fail, unless the selected configuration explicitly requires one.

Application code is materialized as an immutable build bound to the verified Git commit/tree rather than executed from a mutable checkout. The stable launcher points to that build only after environment and application proofs pass. Development-source mode may run a mutable tree but cannot issue verified readiness evidence.

## Ollama and Model Readiness

Bootstrap installs or locates Ollama, starts it only through its supported local mechanism, and probes its loopback API. It does not enable cloud operation.

At least one usable local model is required for the final inference proof. A versioned repository manifest selects the smallest reviewed general-purpose model compatible with the supported host and states its exact immutable model identity, expected download-size bound, and available license/source information. If no acceptable model exists, bootstrap shows this evidence and asks once before pulling it. Noninteractive execution returns `ACTION REQUIRED` with a resume command. The bootstrap never generates or changes this trust manifest during installation.

The model proof performs a bounded local generation with a deterministic small prompt, timeout, and output-shape check. A process responding on the Ollama port without a valid Ollama protocol response is treated as a conflict.

## Local Identity and CLI Authentication

Bootstrap initializes JSON_CODR through supported identity APIs or services, never through direct database edits. It securely prompts for a user-chosen password and creates one permanent Administrator account with full application access. The account, password, browser sessions, and CLI credentials do not expire in the initial non-production mode, though they remain manually revocable. No password, session, or bearer credential is printed, logged, or written to a receipt.

The UI, CLI status, bootstrap summary, and receipt visibly label this as non-production credential policy. A future explicit production-mode flag will require a password reset and enforce credential/session expiration; that later mode is outside this implementation. Bootstrap never silently converts an existing installation between modes.

After the server is healthy, bootstrap invokes the canonical CLI authentication flow and verifies the protected credential store. The CLI smoke test runs as the Administrator through the default endpoint and submits a bounded inference request with a fixed prompt, fixed capability/operation, no filesystem mutation, a strict timeout, and an expected response-shape assertion.

## GitHub Readiness

GitHub support uses the installed `gh` executable and its credential store. Bootstrap never reads or persists the token.

If GitHub is enabled:

- verify `gh` package identity and version;
- inspect `gh auth status` using sanitized output;
- if unauthenticated, start the official browser/device login interactively;
- display and confirm the authenticated host and account;
- perform a read-only `gh api user` proof;
- compare the repository's normalized remotes with the authenticated host;
- perform a read-only `git ls-remote` against the selected remote;
- never push, create a repository, change a remote, or select an account silently.

When multiple remotes, hosts, or authenticated accounts exist, bootstrap requires an explicit interactive selection and confirmation. A ZIP/no-remote source cannot pass trusted-source mode; development-source mode must use `-NoGitHub` or explicitly select a read-only remote without modifying Git configuration.

Authentication cancellation leaves local JSON_CODR usable and records GitHub as explicitly incomplete. The default command exits nonzero until the user either completes GitHub login or reruns with `-NoGitHub`.

## End-to-End Readiness Proof

Success requires fresh evidence from the installed paths:

1. canonical configuration and version agree across launcher, server, CLI, and receipt;
2. supervised server process starts without using Codex;
3. loopback health endpoint returns the expected installation and revision challenge;
4. browser root returns the expected application and required static assets;
5. CLI status succeeds using its default endpoint;
6. CLI credential login/status succeeds;
7. a bounded CLI task completes through the task API;
8. Ollama completes a bounded local inference;
9. when enabled, GitHub identity and remote read proofs succeed;
10. shutdown/restart preserves configuration and the same proofs succeed again.

The proof uses bounded timeouts and terminates only processes created by the bootstrap. It must distinguish unavailable, refused, protocol-invalid, authentication-required, permission-required, and application-error states.

## Reports and Exit Codes

The human report ends with exactly one of:

- `READY`: web, CLI, local inference, and selected integrations are proven;
- `READY (LOCAL ONLY)`: valid only when `-NoGitHub` was explicit;
- `ACTION REQUIRED`: a safe interactive action such as model-license confirmation or GitHub login remains;
- `BLOCKED`: installation or proof failed, with the failed phase and exact repair command.

Stable exit classifications distinguish success, action required, prerequisite trust failure, privilege failure, port conflict, dependency failure, server failure, identity/auth failure, inference failure, and GitHub failure.

Reports redact secrets structurally, not through best-effort string replacement. Raw subprocess output is bounded and sanitized before persistence.

`-NoStart` can report only `ACTION REQUIRED` with static prerequisites verified; it never emits `READY` or a readiness receipt. The normal successful bootstrap leaves a detached stable supervisor running under the unelevated user, with bounded logs under the data root. The report supplies exact status, stop, start, and restart commands. Closing the bootstrap console does not terminate the service; uninstall or stop operations affect only the recorded supervisor identity.

Before downloading or materializing, bootstrap computes required disk space from manifest bounds plus rollback headroom. Network operations use bounded connection and overall timeouts, preserve proxy settings without logging proxy credentials, validate TLS normally, and classify offline, proxy, TLS, partial-download, and disk-full failures. Bootstrap deletes only partial artifacts owned by its current run.

## Testing and Release Gate

Testing includes:

- unit tests for manifest validation, planning, redaction, canonical configuration, state recovery, and exit classification;
- mocked installer tests for missing, old, corrupt, wrong-publisher, and interrupted prerequisites;
- tests proving the elevated worker rejects operations outside its manifest plan;
- port-conflict and false-health-server tests;
- clean VM tests for supported Windows versions and architectures;
- rerun tests after every phase is forcibly interrupted;
- paths containing spaces and non-ASCII characters;
- offline, proxy, TLS, disk-full, UAC-cancelled, and reboot-required behavior;
- no-model and failed-model-pull behavior;
- GitHub signed-out, wrong-account, multiple-account, denied-scope, and network-failure behavior;
- a no-Codex VM assertion that Codex executables, directories, and credentials are absent;
- full web/CLI/Ollama/GitHub readiness and restart proof.

A release is not described as first-run ready until a clean, supported Windows VM completes the documented command from clone to final readiness. CI may test deterministic logic, but the release evidence must include an ephemeral Windows VM integration run and its sanitized receipt.

Dependency lock files are release-owned, committed review artifacts with Python-version and architecture markers for the supported host. Bootstrap consumes them with hashes and never resolves or regenerates them. Canonical version/configuration work must land before readiness proofs; bootstrap logic never hardcodes a release number.

## Documentation

README setup begins with the single bootstrap command and clearly labels manual installation as troubleshooting, not the primary path. It documents:

- trusted sources and machine changes;
- disk and model-download expectations;
- when UAC and GitHub/Ollama interaction occur;
- local-only mode;
- repair and check commands;
- receipt/report locations;
- uninstall boundaries and which user data is preserved.

All version claims are generated or checked against the canonical version source.

## Builder Discretion

The builder may choose the internal PowerShell module layout, journal serialization format, exact environment ID encoding, and test-fixture framework. These choices must preserve the trust allowlist, privilege separation, idempotency, deterministic recovery, canonical configuration, credential ownership, loopback-only server, and end-to-end proof requirements above.
