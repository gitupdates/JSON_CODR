# Task 1 Report — Canonical Runtime Configuration and Trusted Source

## Implementation

- Added `config/runtime.json` as the strict, versioned runtime contract for the application version, loopback host/port, API paths, supported Python versions, default root segments, and declared `JSON_CODR_*` inputs.
- Added `web_app.runtime_config.RuntimeConfig`, including strict schema validation, undeclared-environment rejection, canonical URL/path accessors, and a stable SHA-256 receipt digest that includes explicit active overrides.
- Moved the application version and CLI defaults to `RuntimeConfig`; HTTP status/task requests consume the configured API paths.
- Converted `run_web.ps1` to parse the JSON contract before interpreter selection, preserving loopback `127.0.0.1:8765`, supervised startup, and existing data-root/pointer behavior.
- Added `Get-JsonCodrSourceEvidence` to `scripts/bootstrap/SourceTrust.psm1`. It is read-only: it records normalized `origin`, HEAD commit/tree, a bootstrap-manifest digest, trust state, and a deterministic reason. Normal mode requires a clean tree and a commit reachable from `origin`; development mode remains visibly `development`.
- Preserved the isolated-update fail-closed version check: `ArtifactMaterializer` now accepts only either a literal version or the exact `RuntimeConfig.load().version` AST shape, then reads only `config/runtime.json`; it never imports candidate code.
- Included the approved first-run design and implementation plan in the task commit.

## RED / GREEN Evidence

### Runtime configuration

- **RED:** `python -m unittest test_runtime_config.py test_run_web.py test_version.py -v` failed because `web_app.runtime_config` did not exist.
- **GREEN:** the same focused group passed after the loader and consumers were added.

### Source trust

- **RED:** `python -m unittest test_bootstrap_source_trust.SourceTrustTests.test_clean_commit_reachable_from_origin_is_trusted -v` failed because `scripts/bootstrap/SourceTrust.psm1` and `Get-JsonCodrSourceEvidence` did not exist.
- **GREEN:** `python -m unittest test_bootstrap_source_trust.py -v` passed all clean, dirty, detached, wrong-remote-role, no-Git, development override, SSH normalization, spaced-path, and non-ASCII-path cases.

### Isolated update compatibility

- **RED:** `python -m unittest test_update_launcher.UpdateLauncherTests.test_materializer_reads_the_canonical_runtime_version_without_executing_candidate_code -v` failed with `PermissionError: candidate version is not a literal APP_VERSION assignment`.
- **GREEN:** `python -m unittest test_update_launcher.py -v` passed all 8 update-launcher tests after the strict canonical-configuration AST path was added.

### CLI credential fixture migration

- A broader CLI run exposed one credential fixture still bound to the retired `http://127.0.0.1:8772` default. It was migrated to `RuntimeConfig.load().url`; `python -m unittest test_core_cli.py -v` then passed all 12 tests.

## Verification

- `python -m unittest test_runtime_config.py test_run_web.py test_version.py test_bootstrap_source_trust.py test_core_cli.py test_cli_identity.py test_github_cli.py test_update_launcher.py test_update_supervisor.py -v` — **66 tests passed**.
- `python -m py_compile web_app/runtime_config.py web_app/core/cli.py web_app/version.py test_runtime_config.py test_bootstrap_source_trust.py test_run_web.py test_version.py test_core_cli.py` — passed.
- PowerShell parser check for `run_web.ps1` and `scripts/bootstrap/SourceTrust.psm1` — passed.
- `git diff --check` — passed; Git emitted only pre-existing line-ending conversion warnings.

## Files

- Added: `config/runtime.json`, `web_app/runtime_config.py`, `scripts/bootstrap/SourceTrust.psm1`, `test_runtime_config.py`, `test_bootstrap_source_trust.py`.
- Updated: `run_web.ps1`, `web_app/core/cli.py`, `web_app/version.py`, `web_app/core/update_launcher.py`, `test_run_web.py`, `test_version.py`, `test_core_cli.py`, `test_update_launcher.py`.
- Included: `docs/superpowers/specs/2026-11-24-first-run-bootstrap-design.md`, `docs/superpowers/plans/2026-11-24-first-run-bootstrap.md`.

## Self-review

- The source-evidence module invokes only read-only Git commands (`rev-parse`, `config --get`, `status`, and `branch -r --contains`); it does not fetch, reset, checkout, write Git configuration, or mutate refs.
- Untrusted and development evidence are intentionally distinct. Dirty, detached-unreachable, missing-origin, and extracted sources cannot become `trusted`.
- Existing supervisor/CAS/rollback regression tests passed. The version materializer remains static and fail-closed rather than executing candidate code.
- Launcher host and port retain their approved loopback values. No service was started, activated, published, or pushed.

## Concerns

- The full discovery command `python -m unittest` exceeded bounded foreground waits. I stopped only the hidden verification process because the task prohibits touching the service on port 8765 and an unrestricted discovery run may include integration tests. The 66-test focused/runtime/security regression group above is fresh and passing.
- The required pre-existing untracked `.tmp/` directory is preserved. Consequently, normal source evidence for this *current* working tree is correctly `untrusted` until that unrelated directory is removed or ignored by an explicit future policy; development mode remains available and visibly unverified.
