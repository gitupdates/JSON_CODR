from __future__ import annotations

import argparse
import asyncio
import json
import shutil
import subprocess
from pathlib import Path

from web_app.core.mcp_stdio_backend import load_mcp_server_configs
from web_app.core.rea_acquisition import NpmReaInstaller, ReaAcquirer, ReaReleaseMetadata
from web_app.core.rea_provider_state import ReaProviderStore
from web_app.core.rea_update_service import ReaUpdateService
from web_app.core.rea_verification import ReaCandidateVerifier, ReaProbePolicy
from web_app.core.provider_compatibility import CompatibilityLayer, ProviderUpdateRequest
from web_app.core.rea_compatibility import ReaCompatibilityAdapter


def discover_npm_release(version: str, *, npm: str = "npm.cmd", runner=subprocess.run) -> ReaReleaseMetadata:
    result = runner(
        [npm, "view", f"rea-agents@{version}", "version", "dist.integrity", "dist.tarball", "--json"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=60,
    )
    if result.returncode != 0:
        raise RuntimeError(f"npm metadata lookup failed with exit code {result.returncode}")
    document = json.loads(result.stdout)
    return ReaReleaseMetadata(
        package="rea-agents",
        version=str(document.get("version", "")),
        integrity=str(document.get("dist.integrity", "")),
        registry="https://registry.npmjs.org",
        tarball=str(document.get("dist.tarball", "")),
    )


def provider_environment(config_path: Path) -> dict[str, str]:
    for config in load_mcp_server_configs(config_path):
        if config.name == "rea":
            return dict(config.env)
    return {}


async def _update_rea(version: str, data_root: Path, approved: bool = False) -> dict:
    provider_root = data_root.resolve() / "providers" / "rea"
    store = ReaProviderStore(provider_root / "state.sqlite")
    try:
        metadata = discover_npm_release(version)
        node = shutil.which("node")
        if node is None:
            raise RuntimeError("Node.js is required to run REA")
        service = ReaUpdateService(
            provider_root,
            store,
            ReaAcquirer(provider_root, store, NpmReaInstaller()),
            ReaCandidateVerifier(
                provider_root,
                store,
                policy=ReaProbePolicy(frozenset({"inspect_analysis_settings"}), "inspect_analysis_settings"),
                node_path=node,
                environment=provider_environment(data_root / "mcp_servers.json"),
            ),
        )
        service.recover()
        activation = await service.reinstall(metadata, approved=approved)
        evidence_path = provider_root / "versions" / activation.version / "probe-evidence.json"
        evidence = json.loads(evidence_path.read_text(encoding="utf-8")) if evidence_path.is_file() else {}
        return {"activation": activation.__dict__, "evidence": evidence, "provider_root": str(provider_root)}
    finally:
        store.close()


async def update(version: str, data_root: Path, *, approved: bool = False) -> dict:
    layer = CompatibilityLayer([ReaCompatibilityAdapter(data_root, _update_rea)])
    activation = await layer.update(ProviderUpdateRequest(
        provider_id="rea", version=version, approve_major=approved
    ))
    return {
        "activation": {
            "version": activation.version,
            "generation": activation.generation,
        },
        "evidence": dict(activation.evidence.details),
        "provider_root": str(data_root.resolve() / "providers" / "rea"),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Install and verify an exact REA provider release")
    parser.add_argument("--version", required=True)
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--approve-major", action="store_true")
    arguments = parser.parse_args()
    print(json.dumps(asyncio.run(update(arguments.version, arguments.data_root, approved=arguments.approve_major)), indent=2))


if __name__ == "__main__":
    main()
