from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


MutationClassification = Literal[
    "read_only_compatibility", "interactive_mutation", "autonomous_mutation"
]


@dataclass(frozen=True)
class MutationRouteRecord:
    method: str
    path: str
    classification: MutationClassification
    scope: str | None


def _assign(
    target: dict[tuple[str, str], tuple[MutationClassification, str]],
    scope: str,
    *routes: tuple[str, str],
    classification: MutationClassification = "interactive_mutation",
) -> None:
    for route in routes:
        target[route] = (classification, scope)


def _known_assignments() -> dict[tuple[str, str], tuple[MutationClassification, str]]:
    assignments: dict[tuple[str, str], tuple[MutationClassification, str]] = {}
    _assign(assignments, "agent.launch", ("POST", "/mcp"))
    _assign(
        assignments, "component.install",
        ("POST", "/api/components/plan"),
        ("POST", "/api/components/install/{plan_id}"),
        ("POST", "/api/components/{component_id}/disable"),
        ("POST", "/api/components/{component_id}/rollback"),
    )
    _assign(
        assignments, "session.write",
        ("POST", "/api/projects/{project_id}/memory"),
        ("POST", "/api/projects/{project_id}/memory/{memory_id}/revoke"),
        ("POST", "/api/sessions"),
        ("POST", "/api/sessions/{session_id}/conversation"),
        ("POST", "/api/sessions/{session_id}/skill-recommendations"),
        ("PATCH", "/api/sessions/{session_id}/skill-routing"),
        ("DELETE", "/api/sessions/{session_id}"),
        ("POST", "/api/sessions/{session_id}/attachments"),
        ("POST", "/api/sessions/{session_id}/clipboard-text"),
        ("POST", "/api/sessions/{session_id}/attachments/{attachment_id}/retry"),
        ("PATCH", "/api/sessions/{session_id}/skills"),
        ("PATCH", "/api/sessions/{session_id}/attachments/{attachment_id}"),
        ("DELETE", "/api/sessions/{session_id}/attachments/{attachment_id}"),
    )
    _assign(
        assignments, "agent.launch",
        ("POST", "/api/tasks"),
        ("POST", "/api/tasks/live"),
        ("POST", "/api/tasks/{task_id}/plans/{plan_id}/revise"),
        ("POST", "/api/tasks/{task_id}/plans/{plan_id}/steps/{step_id}/revise"),
        ("POST", "/api/tasks/{task_id}/steer"),
        ("POST", "/api/tasks/{task_id}/cancel"),
        ("POST", "/api/tasks/{task_id}/approve"),
        ("POST", "/api/tasks/{task_id}/retry"),
        ("POST", "/api/tasks/{task_id}/restore"),
        ("WEBSOCKET", "/ws/tasks"),
        ("POST", "/api/git-broker/grants"),
        ("DELETE", "/api/git-broker/grants/{grant_id}"),
        ("POST", "/api/git-broker/tasks"),
        ("POST", "/api/git-broker/adapter"),
        ("POST", "/api/project-workspace/run"),
        ("POST", "/api/workspace/tasks"),
        ("POST", "/api/coding-agents/grants"),
        ("DELETE", "/api/coding-agents/grants/{grant_id}"),
        ("POST", "/api/coding-agents/launch"),
        ("POST", "/api/ag-ui/run"),
        ("POST", "/v1/chat/completions"),
        ("POST", "/api/chat"),
    )
    _assign(
        assignments, "session.write",
        ("POST", "/api/connections/scan"),
        ("POST", "/api/connections/{connection_id:path}/preview"),
        ("POST", "/api/connections/{connection_id:path}/test"),
        ("POST", "/api/connections/{connection_id:path}/recover"),
    )
    _assign(
        assignments, "agent.launch",
        ("POST", "/api/benchmarks/baseline"),
        ("POST", "/api/model-runs"),
        ("POST", "/api/model-runs/{run_id}/cancel"),
        ("POST", "/api/hardware/detect"),
        ("POST", "/api/hardware/probe"),
        ("POST", "/api/hardware/restore-cpu"),
        ("DELETE", "/api/hardware/benchmarks"),
        ("POST", "/api/hardware/benchmarks"),
        ("POST", "/api/integrity-benchmarks"),
        ("POST", "/api/localperf/packages/preview"),
        ("POST", "/api/localperf/packages/import"),
    )
    _assign(
        assignments, "session.write",
        ("POST", "/api/identity/login"),
        ("POST", "/api/identity/logout"),
    )
    _assign(
        assignments, "component.install",
        ("POST", "/api/inference/models/install"),
        ("POST", "/api/sessions/{session_id}/hardware/{provider}/install-proposal"),
    )
    _assign(assignments, "session.write", ("PATCH", "/api/settings"))
    _assign(
        assignments, "session.write",
        ("POST", "/api/skills/scan"),
        ("POST", "/api/skills/scan-upload"),
        ("POST", "/api/skills/scan-known"),
        ("POST", "/api/skills/install-discovery"),
        ("POST", "/api/skills/github/preview"),
        ("POST", "/api/skills/github/install"),
        ("POST", "/api/sessions/{session_id}/attachments/{attachment_id}/skill-preview"),
        ("POST", "/api/sessions/{session_id}/attachments/{attachment_id}/skill-install"),
        ("POST", "/api/skills/deduplicate"),
        ("PATCH", "/api/skills/{pack_id}/{skill_id}"),
        ("PATCH", "/api/skills/{pack_id}"),
        ("DELETE", "/api/skills/{pack_id}"),
    )
    _assign(
        assignments, "git.edit",
        ("POST", "/api/github/auth/login"),
        ("POST", "/api/github/auth/login/{session_id}/cancel"),
        ("POST", "/api/github/repositories"),
        ("PATCH", "/api/github/repos/{owner}/{repository}"),
        ("DELETE", "/api/github/repos/{owner}/{repository}"),
        ("POST", "/api/github/repos/{owner}/{repository}/issues"),
        ("PATCH", "/api/github/repos/{owner}/{repository}/issues/{number}"),
        ("POST", "/api/github/repos/{owner}/{repository}/issues/{number}/comments"),
        ("POST", "/api/github/repos/{owner}/{repository}/branches"),
        ("DELETE", "/api/github/repos/{owner}/{repository}/branches/{branch:path}"),
        ("POST", "/api/github/repos/{owner}/{repository}/pulls"),
        ("PATCH", "/api/github/repos/{owner}/{repository}/pulls/{number}"),
        ("POST", "/api/github/repos/{owner}/{repository}/pulls/{number}/merge"),
        ("POST", "/api/github/repos/{owner}/{repository}/releases"),
        ("PATCH", "/api/github/repos/{owner}/{repository}/releases/{release_id}"),
        ("DELETE", "/api/github/repos/{owner}/{repository}/releases/{release_id}"),
        ("POST", "/api/github/local/clone"),
        ("POST", "/api/github/local/fetch"),
        ("POST", "/api/github/local/pull"),
        ("POST", "/api/github/local/check-build"),
        ("POST", "/api/github/local/update-build"),
        ("POST", "/api/github/local/branch"),
        ("POST", "/api/github/local/stage"),
    )
    _assign(assignments, "git.commit", ("POST", "/api/github/local/commit"))
    _assign(assignments, "git.push", ("POST", "/api/github/local/push"))
    _assign(
        assignments, "terminal.write",
        ("POST", "/api/terminals"),
        ("POST", "/api/terminals/{terminal_id}/interrupt"),
        ("DELETE", "/api/terminals/{terminal_id}"),
        ("POST", "/api/sessions/{session_id}/action-proposals/{proposal_id}/approve"),
        ("POST", "/api/sessions/{session_id}/action-proposals/{proposal_id}/confirm-destructive"),
        ("POST", "/api/sessions/{session_id}/action-proposals/{proposal_id}/reject"),
        ("WEBSOCKET", "/ws/terminals/{terminal_id}"),
    )
    _assign(
        assignments, "system.update",
        ("POST", "/api/updates/candidates"),
        ("POST", "/api/updates/candidates/{candidate_id}/stage"),
        ("POST", "/api/updates/candidates/{candidate_id}/modified"),
        ("POST", "/api/updates/candidates/{candidate_id}/verify"),
        ("POST", "/api/updates/candidates/{candidate_id}/commit"),
        ("POST", "/api/updates/candidates/{candidate_id}/publish"),
        ("POST", "/api/updates/candidates/{candidate_id}/health"),
        ("POST", "/api/updates/candidates/{candidate_id}/reconcile"),
        ("POST", "/api/updates/candidates/{candidate_id}/quarantine"),
        ("POST", "/api/updates/candidates/{candidate_id}/scope-approval"),
        classification="autonomous_mutation",
    )
    _assign(
        assignments, "system.activate",
        ("POST", "/api/updates/candidates/{candidate_id}/activate"),
        classification="autonomous_mutation",
    )
    _assign(
        assignments, "system.rollback",
        ("POST", "/api/updates/candidates/{candidate_id}/rollback"),
        classification="autonomous_mutation",
    )
    _assign(
        assignments, "session.write",
        ("POST", "/api/connections/scan"),
        ("POST", "/api/connections/{connection_id:path}/preview"),
        ("POST", "/api/connections/{connection_id:path}/test"),
        ("POST", "/api/localperf/packages/preview"),
        ("POST", "/api/skills/github/preview"),
        ("POST", "/api/sessions/{session_id}/attachments/{attachment_id}/skill-preview"),
        ("POST", "/api/github/local/check-build"),
        classification="read_only_compatibility",
    )
    return assignments


def _routes(router, prefix: str = ""):
    for route in router.routes:
        if type(route).__name__ == "_IncludedRouter":
            include_prefix = getattr(route.include_context, "prefix", "") or ""
            yield from _routes(route.original_router, prefix + include_prefix)
            continue
        path = prefix + str(getattr(route, "path", ""))
        methods = tuple(sorted(getattr(route, "methods", ()) or ()))
        if type(route).__name__ == "APIWebSocketRoute":
            yield route, "WEBSOCKET", path
        for method in methods:
            if method in {"POST", "PUT", "PATCH", "DELETE"}:
                yield route, method, path


def bind_mutation_route_metadata(application) -> None:
    """Attach the same policy records consumed by runtime enforcement and inventory."""
    assignments = _known_assignments()
    missing = []
    for route, method, path in _routes(application):
        assignment = assignments.get((method, path))
        if assignment is None:
            missing.append(f"{method} {path}")
            continue
        policies = dict(getattr(route, "mutation_policies", {}))
        policies[method] = MutationRouteRecord(method, path, assignment[0], assignment[1])
        route.mutation_policies = policies
    if missing:
        raise ValueError("unassigned mutation route(s): " + ", ".join(sorted(missing)))


def inventory_mutation_routes(application) -> tuple[MutationRouteRecord, ...]:
    bind_mutation_route_metadata(application)
    records = []
    seen = set()
    for route, method, _path in _routes(application):
        record = getattr(route, "mutation_policies", {}).get(method)
        if record is not None and (record.method, record.path) not in seen:
            records.append(record)
            seen.add((record.method, record.path))
    return tuple(sorted(records, key=lambda item: (item.method, item.path)))
