from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tomllib
import venv
from pathlib import Path
from uuid import uuid7

from web_app.core.component_registry import ComponentPlan
from web_app.core.component_acquisition import _file_sha256, _tree_digest
from web_app.core.contracts import FrozenContract
from web_app.core.component_normalization import persist_installation_report


class InstalledRuntime(FrozenContract):
    component_id: str
    runtime_root: str
    runtime_kind: str
    interpreter: str | None = None
    entry_points: dict[str, tuple[str, ...]]


class ComponentRuntimeInstaller:
    def install(self, plan: ComponentPlan, source_root: str | Path, runtime_root: str | Path) -> InstalledRuntime:
        source = Path(source_root).resolve()
        base = Path(runtime_root).resolve()
        base.mkdir(parents=True, exist_ok=True)
        staging = base / f".{plan.component_id}-{uuid7()}.staging"
        destination = base / plan.component_id / plan.plan_id
        staging.mkdir(parents=True)
        try:
            copied = staging / "source"
            shutil.copytree(source, copied, symlinks=True)
            if _tree_digest(copied) != plan.content_digest:
                raise ValueError("component source no longer matches the approved content digest")
            if plan.runtime_kind == "python":
                return self._install_python(plan, copied, staging, destination)
            if plan.runtime_kind == "node":
                package = json.loads((copied / "package.json").read_text(encoding="utf-8"))
                is_resolved_coordinate = plan.source_kind.value == "node"
                if not is_resolved_coordinate and (package.get("dependencies") or package.get("optionalDependencies")):
                    if not (copied / "package-lock.json").is_file():
                        raise ValueError("Node components with dependencies require package-lock.json")
                    completed = subprocess.run(
                        ["npm", "ci", "--ignore-scripts", "--no-audit", "--no-fund"], cwd=copied,
                        capture_output=True, text=True, timeout=300,
                    )
                    if completed.returncode:
                        raise RuntimeError((completed.stderr or completed.stdout).strip())
            commands = self._commands(plan, copied)
            resolved_commands = {name: tuple(_replace_root(argv, staging, destination)) for name, argv in commands.items()}
            (staging / "runtime.json").write_text(json.dumps({key: list(value) for key, value in resolved_commands.items()}), encoding="utf-8")
            persist_installation_report(
                staging, runtime_root=destination, approved_report=plan.normalization,
                ecosystem=plan.runtime_kind, coordinate=plan.source,
                declared_command_names=list(resolved_commands),
                native_commands=_observed_native_commands(plan, staging, destination, resolved_commands),
                effective_commands={name: list(argv) for name, argv in resolved_commands.items()},
            )
            destination.parent.mkdir(parents=True, exist_ok=True)
            os.replace(staging, destination)
            return InstalledRuntime(
                component_id=plan.component_id, runtime_root=str(destination), runtime_kind=plan.runtime_kind,
                entry_points=resolved_commands,
            )
        except BaseException:
            shutil.rmtree(staging, ignore_errors=True)
            raise

    def _install_python(self, plan: ComponentPlan, source: Path, staging: Path, destination: Path) -> InstalledRuntime:
        environment = staging / "venv"
        venv.EnvBuilder(with_pip=True, clear=True).create(environment)
        python = environment / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        resolution_path = source / "component-resolution.json"
        if plan.source_kind.value == "python":
            if not resolution_path.is_file():
                raise ValueError("registry Python package is missing its trusted resolution manifest")
            resolution = json.loads(resolution_path.read_text(encoding="utf-8"))
            requirements = staging / "requirements.txt"
            lines = []
            for artifact in resolution["artifacts"]:
                wheel = source / "artifacts" / artifact["filename"]
                if _file_sha256(wheel) != artifact["sha256"]:
                    raise ValueError("package artifact no longer matches its approved hash")
                lines.append(f'{artifact["name"]}=={artifact["version"]} --hash=sha256:{artifact["sha256"]}')
            requirements.write_text("\n".join(lines) + "\n", encoding="utf-8")
            command = [
                str(python), "-m", "pip", "install", "--disable-pip-version-check", "--no-index",
                "--find-links", str(source / "artifacts"), "--require-hashes", "--only-binary=:all:",
                "--requirement", str(requirements),
            ]
        else:
            resolution = None
            wheelhouse = staging / "wheelhouse"
            wheelhouse.mkdir()
            built = subprocess.run(
                [
                    sys.executable, "-m", "pip", "wheel", "--disable-pip-version-check",
                    "--no-deps", "--no-build-isolation", "--wheel-dir", str(wheelhouse), str(source),
                ],
                capture_output=True, text=True, timeout=300,
            )
            if built.returncode:
                raise RuntimeError((built.stderr or built.stdout).strip())
            wheels = tuple(wheelhouse.glob("*.whl"))
            if len(wheels) != 1:
                raise RuntimeError("component build did not produce exactly one wheel")
            command = [
                str(python), "-m", "pip", "install", "--disable-pip-version-check",
                "--no-index", "--no-deps", str(wheels[0]),
            ]
        completed = subprocess.run(command, capture_output=True, text=True, timeout=300)
        if completed.returncode:
            raise RuntimeError((completed.stderr or completed.stdout).strip())
        if resolution is not None:
            scripts = resolution.get("entry_points", {})
            distribution_name = resolution["coordinate"].split("==", 1)[0]
        else:
            document = tomllib.loads((source / "pyproject.toml").read_text(encoding="utf-8"))
            scripts = document.get("project", {}).get("scripts", {})
            distribution_name = document.get("project", {}).get("name")
        commands = {}
        for name in plan.entry_points:
            invocation = (
                "from importlib.metadata import distribution; import sys; "
                f"ep=next(ep for ep in distribution({distribution_name!r}).entry_points "
                f"if ep.group == 'console_scripts' and ep.name == {name!r}); sys.exit(ep.load()())"
            )
            commands[name] = (str(python), "-c", invocation)
        resolved_commands = {name: tuple(_replace_root(argv, staging, destination)) for name, argv in commands.items()}
        (staging / "runtime.json").write_text(
            json.dumps({name: list(argv) for name, argv in resolved_commands.items()}), encoding="utf-8"
        )
        persist_installation_report(
            staging, runtime_root=destination, approved_report=plan.normalization,
            ecosystem="python", coordinate=plan.source,
            declared_command_names=list(resolved_commands),
            native_commands=_observed_native_commands(plan, staging, destination, resolved_commands),
            effective_commands={name: list(argv) for name, argv in resolved_commands.items()},
        )
        destination.parent.mkdir(parents=True, exist_ok=True)
        os.replace(staging, destination)
        return InstalledRuntime(
            component_id=plan.component_id, runtime_root=str(destination), runtime_kind="python",
            interpreter=str(destination / "venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")),
            entry_points=resolved_commands,
        )

    @staticmethod
    def recover(runtime_root: str | Path) -> tuple[str, ...]:
        removed = []
        for path in Path(runtime_root).glob(".*.staging"):
            shutil.rmtree(path, ignore_errors=True)
            removed.append(str(path))
        return tuple(removed)

    @staticmethod
    def _commands(plan: ComponentPlan, source: Path) -> dict[str, tuple[str, ...]]:
        commands = {}
        for name in plan.entry_points:
            candidates = [source / f"{name}.exe", source / f"{name}.cmd", source / f"{name}.bat", source / name]
            target = next((candidate for candidate in candidates if candidate.is_file()), None)
            if target is not None:
                commands[name] = (str(target),)
        if plan.runtime_kind == "node":
            resolution_path = source / "component-resolution.json"
            if plan.source_kind.value == "node":
                resolution = json.loads(resolution_path.read_text(encoding="utf-8"))
                bins = resolution.get("entry_points", {})
            else:
                package = json.loads((source / "package.json").read_text(encoding="utf-8"))
                bins = package.get("bin", {})
                if isinstance(bins, str):
                    bins = {package.get("name", "component"): bins}
            node = shutil.which("node.exe") or shutil.which("node")
            if node is None:
                raise RuntimeError("Node.js is required to install Node components")
            commands = {}
            for name, relative in bins.items():
                target = (source / str(relative)).resolve()
                try:
                    target.relative_to(source.resolve())
                except ValueError as error:
                    raise ValueError("Node bin target escapes its approved source") from error
                if not target.is_file():
                    raise ValueError("Node bin target is missing from its approved source")
                commands[name] = (str(Path(node).resolve()), str(target))
        if plan.runtime_kind == "mcp":
            manifest = json.loads((source / "mcp_servers.json").read_text(encoding="utf-8"))
            commands = {
                name: (str(config["command"]), *(str(item) for item in config.get("args", [])))
                for name, config in manifest.get("mcpServers", {}).items()
                if isinstance(config, dict) and isinstance(config.get("command"), str)
            }
        return commands


def _replace_root(argv: tuple[str, ...], old: Path, new: Path) -> tuple[str, ...]:
    return tuple(value.replace(str(old), str(new)) for value in argv)


def _observed_native_commands(
    plan: ComponentPlan, staging: Path, destination: Path,
    effective_commands: dict[str, tuple[str, ...]],
) -> dict[str, list[str]]:
    observed = {}
    if plan.runtime_kind == "python":
        roots = (staging / "venv" / "Scripts", staging / "venv" / "bin")
        suffixes = (".exe", ".cmd", ".bat", "")
    elif plan.runtime_kind == "node":
        roots = (staging / "source" / "node_modules" / ".bin",)
        suffixes = (".cmd", ".exe", "")
    else:
        return {name: list(argv) for name, argv in effective_commands.items()}
    for name in effective_commands:
        candidate = next(
            (root / f"{name}{suffix}" for root in roots for suffix in suffixes if (root / f"{name}{suffix}").is_file()),
            None,
        )
        if candidate is not None:
            observed[name] = [str(candidate).replace(str(staging), str(destination))]
    return observed
