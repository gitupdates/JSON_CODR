from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path


def build_normalization_report(resolution: dict) -> dict:
    ecosystem = resolution.get("ecosystem")
    coordinate = resolution.get("coordinate")
    entry_points = resolution.get("entry_points", {})
    if ecosystem not in {"python", "node"} or not isinstance(coordinate, str):
        raise ValueError("normalization requires a supported resolution manifest")
    if not isinstance(entry_points, dict):
        raise ValueError("normalization entry points must be a mapping")

    separator = "==" if ecosystem == "python" else "@"
    if separator not in coordinate:
        raise ValueError("normalization coordinate is not exact")
    name, version = coordinate.rsplit(separator, 1)
    if not name or not version:
        raise ValueError("normalization coordinate is not exact")

    if ecosystem == "python":
        dependencies = [
            {"name": item["name"], "version": item["version"], "sha256": item["sha256"]}
            for item in resolution.get("artifacts", [])
        ]
        blocked = ["source_builds"]
        launcher = {
            "id": "python-metadata-launcher", "kind": "launcher", "target": "console_scripts",
            "before": "installer-generated console launcher", "after": "importlib.metadata entry-point adapter",
            "required": bool(entry_points),
            "reason": "bind commands to the verified isolated interpreter without relocatable launcher assumptions",
        }
    else:
        dependencies = [
            {key: item[key] for key in ("name", "version", "resolved", "integrity")}
            for item in resolution.get("packages", [])
        ]
        blocked = ["lifecycle_scripts"]
        launcher = {
            "id": "node-verified-bin-launcher", "kind": "launcher", "target": "package.bin",
            "before": "package-manager generated shim", "after": "node <verified-bin-target>",
            "required": bool(entry_points),
            "reason": "execute the integrity-verified bin target without generated platform shims",
        }

    alterations = [{
        "id": "isolated-runtime", "kind": "isolation", "target": "runtime",
        "before": "ambient runtime", "after": "component-scoped runtime",
        "required": True, "reason": "prevent component dependencies from mutating the host runtime",
    }]
    if entry_points:
        alterations.append(launcher)
    return {
        "format": 1,
        "ecosystem": ecosystem,
        "coordinate": coordinate,
        "decision": {
            "mode": "adapted" if entry_points else "native",
            "reason": launcher["reason"] if entry_points else "no command adapter is required",
        },
        "extracted": {
            "identity": {"name": name, "version": version},
            "registry": resolution.get("registry"),
            "dependencies": dependencies,
            "entry_points": entry_points,
            "blocked_behaviors": blocked,
        },
        "alterations": alterations,
    }


def build_native_report(*, ecosystem: str, source: str, entry_points: tuple[str, ...]) -> dict:
    adapted = ecosystem in {"python", "node"} and bool(entry_points)
    if ecosystem == "python":
        launcher = ("installer-generated console launcher", "importlib.metadata entry-point adapter")
    else:
        launcher = ("package-manager generated shim", "absolute node interpreter with verified bin target")
    return {
        "format": 1,
        "ecosystem": ecosystem,
        "coordinate": source,
        "decision": {
            "mode": "adapted" if adapted else "native",
            "reason": "a verified portable command adapter is required" if adapted
            else "the approved component runs without a compatibility adapter",
        },
        "extracted": {
            "identity": {"name": Path(source).name or source, "version": None},
            "registry": None, "dependencies": [],
            "entry_points": {name: name for name in entry_points}, "blocked_behaviors": [],
        },
        "alterations": ([{
            "id": f"{ecosystem}-portable-launcher", "kind": "launcher", "target": "entry_points",
            "before": launcher[0], "after": launcher[1], "required": True,
            "reason": "bind execution to the approved isolated runtime and source tree",
        }] if adapted else []),
    }


def persist_installation_report(
    output_root: Path, *, runtime_root: Path, approved_report: dict, ecosystem: str, coordinate: str,
    declared_command_names: list[str], native_commands: dict[str, list[str]],
    effective_commands: dict[str, list[str]],
) -> dict:
    if approved_report:
        report = deepcopy(approved_report)
    else:
        report = build_native_report(
            ecosystem=ecosystem, source=coordinate, entry_points=tuple(effective_commands),
        )
    report["installation"] = {
        "runtime_root": str(runtime_root),
        "declared_command_names": declared_command_names,
        "native_commands": native_commands,
        "effective_commands": effective_commands,
    }
    (output_root / "normalization.json").write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    return report


def record_verification(runtime_root: str | Path, *, succeeded: bool, exit_code: int, evidence_digest: str, output: str) -> dict:
    path = Path(runtime_root) / "normalization.json"
    report = json.loads(path.read_text(encoding="utf-8"))
    report["verification"] = {
        "succeeded": succeeded, "exit_code": exit_code,
        "evidence_digest": evidence_digest, "output": output,
    }
    path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    return report
