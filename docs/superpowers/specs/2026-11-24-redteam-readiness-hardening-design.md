# Red-Team Readiness Hardening Design

## Intent

Turn JSON_CODR V1.4.1 from a functionally usable development build into a truthful, repeatable local coding appliance. The active target remains a single-user, loopback-only development installation with permanent revocable development credentials. Production mode remains opt-in and must revoke development credentials when it is introduced.

## Goals

- Report the identity and supervision state of the process actually serving the CLI and browser.
- Keep mutable runtime state outside the trusted source checkout without weakening source-integrity checks.
- Select a reviewed installed coding model by capability evidence and exact Ollama digest rather than one hard-coded tag.
- Close loopback authentication gaps and make the future production transition fail closed.
- Prove a real edit, test, Git, and rollback workflow inside a disposable repository.
- Replace repeated in-scope prompts with one immutable, reviewable approval envelope.
- Ship every fix independently: RED test, minimal implementation, focused and regression verification, commit, push, pull, live restart/reload, browser and CLI retest.

## Non-goals

- Multi-user or network service exposure.
- Automatic publication without an explicit publication grant.
- Weakening dirty-tree, exact-origin, CSRF, project-root, Git lease, or rollback controls.
- Deleting the existing `.tmp/` evidence before a verified recoverable migration.

## Architecture

Runtime identity is server-derived and corroborated against launcher/supervisor evidence. Mutable files live under the configured JSON_CODR data root; legacy workspace state is migrated with hashes and a receipt. Bootstrap reads a versioned model policy and proves an installed model by digest and inference probe. Development credentials are explicitly labeled and production activation atomically invalidates them. A disposable-repository verifier exercises the real CLI and project boundaries. Approval envelopes bind a finite set of canonical calls to one principal, project fingerprint, and task revision.

## Release protocol for every fix

1. Add a focused regression that fails for the observed defect.
2. Implement only that fix and pass its focused suite plus affected security tests.
3. Commit one fix, push `main`, pull `main --ff-only`, and prove local/remote SHA equality.
4. Restart the live service from that SHA, reload the in-app browser with the revision, and run one browser/API/CLI smoke test.
5. Record the evidence in the hardening ledger before starting the next fix.

## Acceptance

The final trusted bootstrap check is ready, CLI status is truthful, browser and CLI operate from the same identified build, the disposable coding proof passes without boundary escape, approval prompts do not repeat inside an approved envelope, all affected/full tests pass, and the checkout is clean with runtime data externalized.
