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
from web_app.core.contracts import FrozenContract


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
            if plan.runtime_kind == "python":
                return self._install_python(plan, source, staging, destination)
            copied = staging / "source"
            shutil.copytree(source, copied)
            commands = self._commands(plan, copied)
            (staging / "runtime.json").write_text(json.dumps({key: list(value) for key, value in commands.items()}), encoding="utf-8")
            destination.parent.mkdir(parents=True, exist_ok=True)
            os.replace(staging, destination)
            return InstalledRuntime(
                component_id=plan.component_id, runtime_root=str(destination), runtime_kind=plan.runtime_kind,
                entry_points={name: tuple(_replace_root(argv, staging, destination)) for name, argv in commands.items()},
            )
        except BaseException:
            shutil.rmtree(staging, ignore_errors=True)
            raise

    def _install_python(self, plan: ComponentPlan, source: Path, staging: Path, destination: Path) -> InstalledRuntime:
        environment = staging / "venv"
        venv.EnvBuilder(with_pip=True, clear=True).create(environment)
        python = environment / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        completed = subprocess.run(
            [str(python), "-m", "pip", "install", "--disable-pip-version-check", "--no-deps", str(source)],
            capture_output=True, text=True, timeout=300,
        )
        if completed.returncode:
            raise RuntimeError((completed.stderr or completed.stdout).strip())
        document = tomllib.loads((source / "pyproject.toml").read_text(encoding="utf-8"))
        scripts = document.get("project", {}).get("scripts", {})
        commands = {}
        for name in plan.entry_points:
            target = scripts[name]
            module, function = target.split(":", 1)
            commands[name] = (str(python), "-c", f"from {module} import {function}; {function}()")
        destination.parent.mkdir(parents=True, exist_ok=True)
        os.replace(staging, destination)
        resolved_commands = {name: tuple(_replace_root(argv, staging, destination)) for name, argv in commands.items()}
        (destination / "runtime.json").write_text(
            json.dumps({name: list(argv) for name, argv in resolved_commands.items()}), encoding="utf-8"
        )
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
            package = json.loads((source / "package.json").read_text(encoding="utf-8"))
            bins = package.get("bin", {})
            if isinstance(bins, str):
                bins = {package.get("name", "component"): bins}
            commands = {name: ("node", str(source / relative)) for name, relative in bins.items()}
        return commands


def _replace_root(argv: tuple[str, ...], old: Path, new: Path) -> tuple[str, ...]:
    return tuple(value.replace(str(old), str(new)) for value in argv)
