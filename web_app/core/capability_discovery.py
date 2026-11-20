from __future__ import annotations

from pathlib import Path

from web_app.core.contracts import FrozenContract


class ProjectProfile(FrozenContract):
    project_root: str
    kinds: frozenset[str]
    evidence: dict[str, tuple[str, ...]]
    trust: str = "untrusted_manifest_evidence"


_MARKERS = {
    "python": ("pyproject.toml", "requirements.txt", "setup.py"),
    "node": ("package.json",), "dotnet": ("*.csproj", "*.sln"),
    "java": ("pom.xml", "build.gradle", "build.gradle.kts"), "go": ("go.mod",),
    "rust": ("Cargo.toml",), "containers": ("Dockerfile", "compose.yaml", "docker-compose.yml"),
    "browser": ("playwright.config.*",), "database": ("*.sql",),
    "terraform": ("*.tf",), "bicep": ("*.bicep",),
    "cloudformation": ("template.yaml", "template.yml"),
    "kubernetes": ("deployment.yaml", "deployment.yml", "kustomization.yaml"),
    "helm": ("Chart.yaml",),
}


def discover_project_profile(project_root: str | Path) -> ProjectProfile:
    root = Path(project_root).resolve()
    evidence = {}
    for kind, patterns in _MARKERS.items():
        matches = sorted({path.relative_to(root).as_posix() for pattern in patterns for path in root.glob(pattern) if path.is_file()})
        if matches:
            evidence[kind] = tuple(matches)
    return ProjectProfile(project_root=str(root), kinds=frozenset(evidence), evidence=evidence)
