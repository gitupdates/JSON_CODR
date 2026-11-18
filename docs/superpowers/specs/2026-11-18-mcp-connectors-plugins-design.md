# MCP, Connectors, Skills, and Plugins V1.0.18-alpha.13 Design

## Intent

Give JSON_CODR a provider-neutral extension platform in which:

- a **Skill** is a reusable instruction package rooted at `SKILL.md`;
- a **Skillset** is a routing collection of installed skill references;
- a **Connector** is an authorized MCP connection to tools and data;
- a **Plugin** is an installable bundle for one job function that may contain skills, connector definitions, slash commands, agent profiles, templates, and assets.

The reference image informs this separation, not the branding or any proprietary implementation. JSON_CODR remains model-provider neutral and interoperates through open formats and MCP.

## Goals

- Add Streamable HTTP MCP alongside the existing `stdio` client, with compatible protocol negotiation.
- Add OAuth authorization, secure credential storage, refresh, revocation, and scope display for remote connectors.
- Support local, project, and user connector/plugin scopes with explicit project trust.
- Support MCP tools, resources, prompts, elicitation, notifications, pagination, health, reconnect, and bounded results.
- Add a provider-neutral plugin manifest and lifecycle using the existing acquisition, quarantine, provenance, inspection, installation, and rollback infrastructure.
- Make every plugin contribution visible, independently enableable, and subject to alpha.12 plan/policy gates.
- Preserve the semantic difference between an instruction package, a routing collection, an authenticated connection, and an installable bundle.

## Non-goals

- Copying another product's branding, proprietary connector catalog, hosted authentication service, or private plugin format.
- Treating plugin installation as permission to run commands, authenticate connectors, access credentials, or perform external effects.
- Organization-wide identity, central administration, or team-enforced distribution. Those remain alpha.14.
- Allowing plugins to inject executable browser code into JSON_CODR pages.
- Replacing existing standalone skills, Skillsets, or components with plugins.

## Product model

### Skill

A skill is an instruction-only package with `SKILL.md` as its entry point. It is loaded lazily when explicitly selected, invoked by a declared command, or recommended by deterministic routing. Its capability declarations describe requirements and never grant permission.

### Skillset

A Skillset remains a collection of canonical skill references plus routing terms and attachment hints. It copies no instructions and owns no connector, command, or agent lifecycle. A plugin may contribute Skillsets, but installed Skillsets remain ordinary routing collections.

### Connector

A connector is a configured MCP server plus transport, authentication state, capability inventory, policy state, and health state. Installing or enabling its definition does not authenticate it. Authentication does not approve its tools. Tool execution remains an exact reviewed plan step.

### Plugin

A plugin is one immutable, versioned bundle for a job function. It may contribute:

- skills and Skillsets;
- connector definitions with no embedded secrets;
- slash commands that expand into structured task descriptions or plan templates;
- agent profiles that restrict model-routing preferences and available capabilities;
- templates, schemas, icons, and other passive assets.

A plugin is not an arbitrary code-loading escape hatch. Executable components use the existing inspected component runtime and its declared entry points; frontend assets are passive and rendered by host-owned components.

## Manifest

The root file is `json-codr-plugin.json` with a versioned, strict schema. Required fields are:

- `schemaVersion`;
- stable `id`, human `name`, `version`, and `description`;
- publisher identity and license;
- relative contribution paths;
- declared capability requirements;
- minimum/maximum compatible JSON_CODR version;
- content manifest with path, media type, size, and SHA-256 digest.

Optional contribution arrays are `skills`, `skillsets`, `connectors`, `commands`, `agents`, `templates`, and `assets`. Paths must be relative, normalized, inside the bundle, non-symlink escapes, and present in the content manifest. Unknown top-level keys fail validation until a newer schema explicitly defines them.

Connector definitions may contain server URLs, commands, arguments, environment-variable references, requested OAuth scopes, and tool loading preferences. They may not contain access tokens, refresh tokens, client secrets, passwords, or resolved credential values.

## Installation lifecycle

1. **Acquire** from a reviewed local folder, archive, pinned Git source, or registry coordinate.
2. **Inspect** manifest, paths, sizes, hashes, licenses, compatibility, executable entry points, requested capabilities, connector domains/scopes, and contribution collisions.
3. **Preview** every contribution and permission requirement before installation.
4. **Approve exact digest** using the alpha.12 plan and effect policy.
5. **Quarantine and probe** executable/runtime contributions without activating them.
6. **Install atomically** into an immutable version directory.
7. **Enable separately** at local/project/user scope. Connector authentication and tool policy remain separate actions.
8. **Update** only through a new inspected digest with a contribution and permission diff.
9. **Disable, roll back, or uninstall** without deleting user-created task history or audit evidence.

Partial activation is allowed: a user may enable plugin skills while leaving commands, agents, or connectors disabled. A contribution whose prerequisites are unavailable is shown as unavailable, not silently omitted.

## Scope and precedence

Alpha.13 supports:

1. project-local private configuration;
2. project-shared configuration committed with the project;
3. user configuration across projects.

More specific definitions win only when policy permits them. A project may not shadow an installed component with a different digest without an explicit trust decision. Managed organization definitions and immutable deny rules arrive in alpha.14 and take precedence over all alpha.13 scopes.

## Commands and agent profiles

A slash command is a named, documented input schema that expands into a task description or plan template. Invoking it never executes a shell command or connector call directly. The resulting plan is reviewed under the active alpha.12 policy.

An agent profile declares purpose, instruction references, model-routing preferences, context limits, and a capability allowlist. It cannot grant a capability absent from the host session or broaden the task policy. Delegated execution remains auditable child-task work.

## MCP transport and authorization

- Keep `stdio` for local subprocess servers.
- Add Streamable HTTP for remote servers and negotiate supported protocol versions.
- Treat legacy SSE only as an explicit compatibility mode.
- Validate remote URL scheme, DNS/IP policy, redirects, TLS, response size, content type, protocol messages, Origin behavior, and session lifecycle.
- Implement OAuth protected-resource and authorization-server discovery, authorization code flow with PKCE, state validation, resource indicators, token audience validation, refresh, and revocation.
- Store tokens outside project files using an operating-system protected credential store. Persist only opaque credential references in JSON_CODR state.
- Never forward one connector's token to another origin or accept token passthrough as an MCP authorization strategy.

## MCP feature surface

- **Tools:** discover dynamically, validate schemas, retain server/tool/schema digests, honor policy annotations only as advisory metadata, and execute through exact plan steps.
- **Resources:** searchable picker with explicit selection, URI/provenance display, bounded reads, subscriptions, and change notifications.
- **Prompts:** user-invoked commands rendered through host UI; retrieved content enters the task as attributed instructions, never higher-priority policy.
- **Elicitation:** host-rendered form or URL interaction with cancel/decline support; sensitive fields are not written to task events.
- **Notifications and tasks:** bounded status updates, cancellation, reconnect, and no automatic replay of uncertain effects.
- **Tool search:** defer large tool catalogs and load definitions on demand without changing policy decisions.

## Security and policy

- Installation, enablement, authentication, capability discovery, and execution are separate authorities.
- Unknown tools and effects default to `ask`; blocked tools are removed from model-visible capability lists.
- Plugin provenance is included in plan-step digests but never grants permission.
- Tool schema, server identity, requested OAuth scope, plugin digest, arguments, effect classification, or policy changes invalidate existing approval.
- Read-only annotations permit optimization only after host validation; they do not independently authorize calls.
- Secrets are redacted from logs, events, plans, exports, diagnostics, and frontend state.
- Connector results carry origin labels and are treated as untrusted external content subject to prompt-injection boundaries.
- Passive assets have strict type/size limits; SVG/HTML/script-capable content is sanitized or rejected.

## User interface

The Skills destination becomes **Skills & Plugins** while retaining separate tabs:

- **Skills:** installed instruction packages, routing reason, source, version, enabled state, and edit/replace controls.
- **Skillsets:** routing collections and auto-attachment behavior.
- **Plugins:** job-function bundles, version/provenance, contribution inventory, scope, update diff, enablement, rollback, and uninstall.
- **Connectors:** status, transport, account identity, scopes, tools/resources/prompts, connect/reconnect/revoke, per-tool policy, and diagnostics.

Plugin preview shows every contribution and separates these actions: Install, Enable contributions, Connect account, and Permit tool calls. The interface never presents them as one approval.

Recommended neutral heading: **Skills & plugins: teach JSON_CODR your way.**

## Persistence and audit

Persist immutable plugin versions, content digests, provenance, inspection reports, contribution identities, enablement scope, connector definitions, opaque credential references, OAuth scope grants, tool inventory digests, health transitions, policy decisions, and task execution references. Uninstall removes active files and registrations but retains audit-safe tombstones referenced by past tasks.

## Failure and recovery

- A failed contribution probe leaves the whole new version inactive; the previous version stays available.
- Connector authentication failure never disables unrelated plugin skills.
- Schema drift marks affected tools stale and invalidates pending approvals.
- Mid-call disconnects reconcile before retry and never replay unknown effects automatically.
- A plugin update requiring broader capabilities or OAuth scopes always returns to preview and approval.
- Missing optional prerequisites produce an actionable unavailable state.

## Testing strategy

- Strict manifest/path/hash/license/compatibility validation and malicious-archive tests.
- Atomic install, partial enablement, update diff, rollback, uninstall, collision, and recovery tests.
- Stdio and Streamable HTTP conformance tests across supported protocol revisions.
- OAuth discovery, PKCE, state, redirect, token audience, refresh, revoke, scope escalation, vault, and leakage tests.
- Tools/resources/prompts/elicitation/notifications/pagination/schema-drift tests.
- Plan/policy tests proving plugin origin never grants authority.
- UI accessibility, keyboard, narrow-screen, secret-redaction, and offline diagnostics tests.

## Rollout

1. Land manifest/schema and read-only plugin inspection behind `plugin_platform`.
2. Add atomic local/project/user installation and passive skills/templates.
3. Add commands and constrained agent profiles.
4. Add Streamable HTTP, OAuth, credential vault, and connector UI.
5. Add resources, prompts, elicitation, reconnect, and deferred discovery.
6. Enable by default only after security, migration, Windows, and end-to-end verification.

## Deferred to alpha.14

- organization accounts and administrator roles;
- managed plugin/connector catalogs;
- team-wide distribution and immutable allow/ask/block policy;
- centrally managed connector authentication;
- enterprise audit export and retention policy;
- production parallel delegation, isolated child worktrees, merge review, and durable schedules.
