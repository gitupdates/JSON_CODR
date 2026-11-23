# Staged Autonomous Self-Update Controller

## Intent

JSON_CODR should be able to prepare, verify, publish, and activate its own code changes without handing an LLM unrestricted shell, filesystem, GitHub, or live-install authority. Automatic publication is permitted only when every mandatory isolation, verification, provenance, and health gate succeeds. A failure must leave the currently running build usable and produce evidence an Administrator can audit.

## Goals

- Bind every executable capability to a server-owned risk classification; model output cannot choose its own approval class.
- Authenticate every GitHub, broker, terminal, and coding-agent mutation with a verified account or scoped service credential.
- Perform self-modification only in a dedicated Git worktree created from an observed base commit.
- Require deterministic verification of the final candidate tree before commit or push.
- Push only the exact verified commit to the configured branch with remote-state checks.
- launch the candidate separately, verify API and UI health, then atomically select it as the active build.
- Preserve the prior known-good revision and automatically restore it if activation fails.
- Record durable, tamper-evident evidence for proposal, authorization, edits, checks, publication, activation, and rollback.
- Keep existing direct LLM, chat, CLI, project editing, acceleration, REA, Ghidra, and compatibility-layer paths available.

## Non-goals

- Granting models direct GitHub credentials or unrestricted command execution.
- Treating model assertions, formatted text, or self-reported tests as verification evidence.
- Automatically resolving semantic merge conflicts.
- Updating a dirty live checkout, rewriting published history, or force-pushing.
- Replacing existing project-action approvals for ordinary user projects.

## Anti-goals

- A second independent policy engine that can disagree with BORG policy.
- A self-update path implemented directly in HTTP handlers, chat handlers, or UI code.
- Security labels that describe isolation not actually enforced by the operating system or execution adapter.
- A successful status when the final candidate differs from the tree that was verified.

## Constraints

- Windows is the primary platform; Git worktrees and subprocesses must behave predictably on Windows.
- Existing GitHub authentication remains owned by the local `gh` credential store. JSON_CODR stores only credential references and observed identity/scope evidence.
- The current local service must remain available while a candidate is tested.
- Existing API callers need a compatibility period, but the static `X-JSON-CODR: 1` header cannot authorize mutations.
- Automatic self-update applies only to a repository and branch explicitly assigned to the Administrator-owned update profile.

## Builder-check decisions

### Stable launcher and active-build pointer

The current `run_web.ps1` directly starts the application and is not a safe replacement boundary. Delivery therefore includes a small stable Windows launcher stored outside candidate worktrees and version directories. It owns the active-build pointer, child PID, restart, post-switch health check, and rollback. Candidate code cannot rewrite the launcher or pointer directly; it submits an authenticated activation request. The launcher remains deliberately small and does not contain planning, Git, model, or policy logic.

### Threat model

The boundary must withstand malicious or malformed model output, hostile repository content, compromised verification commands inside a candidate, accidental concurrent servers, interrupted Git/network operations, and an untrusted local web page. It does not claim protection from a Windows Administrator who intentionally alters the program, operating system, Git credential store, DPAPI state, or launcher. Verification subprocesses are untrusted and must receive least privilege; until a Windows restricted-token/container adapter enforces host and network isolation, autonomous profiles may run only fixed, reviewed executables and arguments that do not interpret candidate-controlled command strings.

### Identity trust root

The controller extends the V1.3.9 `IdentityService`: browser sessions remain HTTP-only and CSRF-protected, CLI tokens remain DPAPI-protected, and the verifier remains a distinct service identity. A new self-update service credential is issued to the Administrator-owned service account, stored through the same OS-protected credential mechanism, scoped to the lifecycle capabilities in this design, rotated on a configurable schedule, and independently revocable. Account recovery continues to preserve at least one owner/administrator authority.

### Authoritative repository and remote movement

The Administrator update profile stores an exact GitHub host, repository slug, remote name, branch, local repository root, and whether direct push is permitted. The initial profile targets the currently connected JSON_CODR repository and branch, but no source constant grants authority. Any repository, identity, branch, upstream, or remote-host mismatch blocks the candidate. Remote movement after staging invalidates publication; the candidate must be rebased or restaged and reverified. Direct automatic push is allowed only when the configured branch permits it; otherwise the controller creates a candidate branch and pull request and waits for the configured merge policy.

### Candidate launch contract

The repository exposes one server-owned launch profile containing the Python executable, module/launcher entry point, required environment keys, disposable data-root construction, loopback host, dynamic port, startup deadline, health routes, and cleanup policy. Candidate-controlled files may declare compatible metadata but cannot replace the trusted launch profile. The launched version must report the candidate commit and application version being evaluated.

### Durable orchestration

Candidate transitions extend the existing task command/event store and its ordered, hash-chained events. External Git, verification, launch, activation, and rollback operations are outbox-style effects with deterministic idempotency keys. The controller does not add a second state database or mutable JSON authority.

### Known-good state and migrations

The initial known-good revision is the exact clean commit running when the launcher/controller migration is enabled and passes the full activation health profile. Candidate migrations run only against disposable database copies. Automatic activation is blocked when a migration is not declared backward compatible with the previous build. Irreversible migrations require Administrator approval and an independently verified backup/restore receipt; they are never part of unattended activation.

### Protected verification policy

Verification profiles and repository policy live in Administrator-owned application data outside the candidate repository. Their canonical representation is included in the candidate manifest by digest. Updates to these profiles require a separate authenticated administration operation and cannot be bundled into a candidate self-update. The verifier signs receipts with an OS-protected key reference; the raw key is not available to the candidate process. Rotation preserves prior public verification material so historical receipts remain checkable.

### Compatibility inventory

Implementation begins with a generated inventory of every mutation route: GitHub API writes, local Git writes, broker grants/tasks, coding-agent grants/launches, terminal writes, project actions, component installation, migration, promotion, activation, and rollback. Each route must be classified as read-only, interactive mutation, or autonomous mutation and mapped to an authenticated scope. The static terminal header is removed from mutation authorization in the first release; read-only compatibility is time-limited and visibly deprecated.

## Approaches considered

### Harden the current live-update path

This would add authentication and checks around the existing fast-forward update and broker execution. It is smaller, but the live process would continue modifying the code it is running, and recovery would remain coupled to the component that failed.

### Dedicated staged controller (selected)

Add a service that owns the full candidate lifecycle. Models propose bounded changes; the controller performs worktree creation, final verification, commit, publication, candidate launch, health validation, promotion, and rollback. The controller is the only path allowed to perform an automatic self-update.

### External updater daemon

A separate installed Windows service would provide the strongest process boundary. It also adds packaging, lifecycle, upgrade, and recovery complexity that is premature for the current local build. The internal controller will expose a narrow adapter boundary so this can be introduced later without changing the workflow contract.

## Design

### 1. Identity and authority

All mutation endpoints resolve an `AuthenticatedPrincipal`; the constant terminal header is accepted only for read-only compatibility routes during migration. Browser mutations require the HTTP-only session plus CSRF. CLI calls require a `cli` token. Automatic self-update uses a separate `service` credential issued to the Administrator account and scoped to:

- `project.read`
- `project.edit.staged`
- `verification.run`
- `git.commit.staged`
- `git.push.verified`
- `system.candidate.launch`
- `system.activate.verified`
- `system.rollback`

The raw GitHub token remains in the GitHub CLI credential store. Before publication, the controller records the authenticated login, host, repository permission, and available GitHub scopes where `gh` exposes them. Missing required permission blocks publication.

### 2. Immutable capability registry

The server registers each capability with its canonical operation and risk. Incoming `CapabilityCall` objects identify the capability and arguments; callers cannot supply an authoritative operation. During compatibility migration, a supplied operation must exactly match the registry or the request is rejected.

Initial mappings include:

- `native.read` -> `read`
- `native.write` and `native.edit` -> `bounded_edit`
- `native.shell` -> `command`
- `git.commit` -> `commit`
- `git.push` -> `push`
- `system.activate` -> `activation`
- `system.rollback` -> `rollback`

Policy decisions use only the registry value. Persistent grants include principal, project, capability, canonical operation, argument constraints, and expiry.

### 3. Command execution boundary

Ordinary agent work does not receive arbitrary host shell access. Commands run from named verification profiles containing exact executable paths, argument templates, working-directory rules, timeouts, output limits, environment allowlists, and network policy.

The existing generic `native.shell` is Administrator-interactive by default. Autonomous candidates may invoke only configured verification profiles. The runtime reports the isolation it actually enforces; it must not claim network isolation unless a sandbox adapter actively enforces it. A future Windows container or restricted-token adapter can satisfy stronger profiles without changing the controller.

### 4. Candidate lifecycle

The durable state machine is:

`proposed -> staged -> modified -> verification_pending -> verified -> committed -> published -> health_pending -> healthy -> activated`

Failure states are `rejected`, `verification_failed`, `publication_failed`, `health_failed`, and `rolled_back`.

Each transition is idempotent and persists its input digest and output receipt before the next external effect. Restart recovery resumes safe pending work or marks ambiguous external effects for reconciliation.

### 5. Isolated editing

The controller requires a clean source repository and acquires a cross-process repository lock. It creates a named worktree and candidate branch from the exact base commit. The model may read and patch only inside that worktree through project adapters. Symlinks, reparse points, absolute paths, and project escapes are rejected.

No changes are copied into the live checkout. Untracked additions and deletions are represented by Git state in the candidate worktree.

### 6. Mandatory final verification

Verification profiles are selected server-side from changed paths and repository policy. A candidate cannot commit or push unless:

- all mandatory checks completed successfully;
- the worktree is not mid-merge or mid-rebase;
- no verification process timed out;
- the final Git tree digest equals the verified manifest digest;
- the base and remote branch have not changed incompatibly;
- the candidate contains no uncommitted changes after commit;
- the verification service identity signed the manifest record.

Any edit after verification invalidates the manifest and returns the candidate to `verification_pending`.

### 7. Publication

The controller creates one commit containing exactly the verified tree, fetches the configured remote, and refuses divergence. It pushes with a compare-and-swap expectation against the previously observed remote SHA. Force-push is unsupported. An ambiguous network result is reconciled by querying the remote branch before retrying; publication is idempotent by candidate ID and commit SHA.

### 8. Candidate health and activation

Publication does not activate the build. The controller launches the candidate from its worktree on a separate loopback port and data directory. It verifies:

- process startup and version identity;
- `/openapi.json` and health endpoints;
- identity database compatibility using a disposable copy;
- a read-only model/catalog request;
- static UI loading with no fatal console errors;
- required migration and focused regression profiles.

After health succeeds, activation updates an atomic active-build pointer used by the launcher, restarts through the launcher boundary, and confirms health again. The previous active revision remains recorded as known-good.

### 9. Rollback

Rollback changes the active-build pointer to the previous known-good revision; it does not use `git reset --hard` on a user checkout. If post-activation health fails, rollback is automatic. Candidate worktrees and branches remain quarantined until an Administrator reviews or removes them.

### 10. Git failure recovery

All merge and rebase operations run in candidate worktrees. Failure handlers explicitly abort the operation and persist stderr plus repository state. The live repository is never left mid-rebase. Cross-process locks use an OS-visible lock file containing owner, process, candidate, and expiry metadata; stale locks require verified owner death before recovery.

### 11. Audit and evidence

Candidate events use the durable task event store rather than the mutable Git broker JSON file. Each event includes principal, credential reference, candidate ID, base SHA, remote SHA, tree digest, capability, canonical operation, verification receipt, and resulting commit. Records are hash chained. Secrets and raw credentials are excluded.

The Administrator UI displays candidates, checks, logs, publication receipts, active and previous builds, and explicit quarantine/rollback/remove actions.

### 12. Compatibility and migration

- Existing read-only GitHub status endpoints keep temporary header compatibility.
- Mutation endpoints require authenticated principals immediately.
- Existing model action envelopes are accepted only after server-side operation normalization.
- Existing project grants are migrated to constrained, expiring grants or marked legacy-disabled.
- Existing direct Git operations remain available interactively but cannot be used by the automatic self-update controller.
- Continue/Aider compatibility routes remain optional adapters and do not become policy authorities.

## Verification strategy

Tests must cover hostile and failure cases, not only happy paths:

- spoofed `operation=read` with `native.shell`, write, or edit;
- unauthenticated and wrong-scope Git/agent mutations;
- absolute-path and reparse-point command attempts;
- network use from a no-network verification profile;
- edit after verification invalidating the manifest;
- omitted verification before commit or push;
- remote drift and ambiguous push reconciliation;
- process crash at every durable transition;
- rebase conflict followed by automatic abort;
- two server processes competing for one repository;
- unhealthy candidate and automatic rollback;
- audit-chain validation and credential redaction;
- regression coverage for existing chat, CLI, Ollama, acceleration, skills, REA, Ghidra, GitHub, and Designer access.

## Delivery sequence

1. Authenticate and scope all mutation endpoints.
2. Introduce the immutable capability registry and eliminate caller-owned risk labels.
3. Restrict autonomous commands to named verification profiles.
4. Enforce mandatory final verification in the Git broker.
5. Add durable candidate state, worktree isolation, and cross-process locking.
6. Add compare-and-swap publication and failure reconciliation.
7. Add separate-port health validation, atomic activation, and pointer-based rollback.
8. Migrate compatibility routes and expose Administrator audit controls.

At every step, the existing supervised path remains functional. Automatic self-update stays disabled until the full lifecycle, verifier identity, health checks, and rollback path pass end-to-end validation.
