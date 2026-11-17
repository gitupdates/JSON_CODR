from __future__ import annotations

import json
import shutil
from pathlib import Path
from uuid import uuid7

from web_app.core.credentials import CredentialBroker
from web_app.core.provider_protocol import ProviderLock, ProviderManifest, ProviderProcess


class ProviderManager:
    def __init__(
        self,
        root: str | Path,
        interpreter_resolver,
        installer,
        client_factory,
        *,
        credentials: CredentialBroker | None = None,
    ) -> None:
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self._resolve_interpreter = interpreter_resolver
        self._install = installer
        self._client_factory = client_factory
        self._credentials = credentials or CredentialBroker()
        self._processes: dict[str, ProviderProcess] = {}
        self._clients: dict[str, object] = {}
        self._calls: dict[str, str] = {}

    async def ensure(self, manifest: ProviderManifest) -> ProviderProcess:
        target = self.root / manifest.provider_id
        current = self.lock(manifest.provider_id) if (target / "provider-lock.json").is_file() else None
        if current and current.version == manifest.version and dict(current.packages) == dict(manifest.packages):
            return await self.start(manifest.provider_id)
        python = Path(self._resolve_interpreter(manifest.python_versions))
        staging = self.root / f".{manifest.provider_id}.staging-{uuid7()}"
        backup = self.root / f".{manifest.provider_id}.backup"
        try:
            self._install(manifest, staging, python)
            candidate = ProviderProcess(
                provider_id=manifest.provider_id,
                version=manifest.version,
                root=str(staging),
                python=str(python),
                ready=False,
            )
            client = self._client_factory(candidate)
            probe = await client.request(manifest.probe_operation, {}, timeout=120)
            if not probe.get("ready"):
                raise RuntimeError("provider functional probe failed")
            lock = ProviderLock(
                provider_id=manifest.provider_id,
                version=manifest.version,
                python=str(python),
                packages=manifest.packages,
                network_policy=manifest.network_policy,
                mounts=manifest.mounts,
            )
            (staging / "provider-lock.json").write_text(lock.model_dump_json(indent=2), encoding="utf-8")
            if backup.exists():
                shutil.rmtree(backup)
            if target.exists():
                target.replace(backup)
            staging.replace(target)
            if backup.exists():
                shutil.rmtree(backup)
            process = candidate.model_copy(update={"root": str(target), "ready": True})
            self._processes[manifest.provider_id] = process
            self._clients[manifest.provider_id] = client
            return process
        except Exception:
            if staging.exists():
                shutil.rmtree(staging)
            if backup.exists() and not target.exists():
                backup.replace(target)
            raise

    async def start(self, provider_id: str) -> ProviderProcess:
        lock = self.lock(provider_id)
        process = ProviderProcess(
            provider_id=provider_id,
            version=lock.version,
            root=str(self.root / provider_id),
            python=lock.python,
            ready=True,
        )
        self._processes[provider_id] = process
        self._clients[provider_id] = self._client_factory(process)
        return process

    def lock(self, provider_id: str) -> ProviderLock:
        return ProviderLock.model_validate_json((self.root / provider_id / "provider-lock.json").read_text(encoding="utf-8"))

    async def probe(self, provider_id: str) -> dict:
        process = self._processes.get(provider_id) or await self.start(provider_id)
        return await self._clients[process.provider_id].request("probe", {}, timeout=120)

    async def execute(self, provider_id: str, call_id: str, operation: str, payload: dict) -> dict:
        process = self._processes.get(provider_id) or await self.start(provider_id)
        request = dict(payload)
        references = request.pop("credential_refs", [])
        if references:
            request["credentials"] = {
                reference: self._credentials.resolve_for_adapter(reference) for reference in references
            }
        self._calls[call_id] = provider_id
        try:
            return await self._clients[process.provider_id].request(
                operation, {"call_id": call_id, **request}, timeout=120
            )
        finally:
            self._calls.pop(call_id, None)

    async def cancel(self, call_id: str) -> None:
        provider_id = self._calls.get(call_id)
        if provider_id is None:
            provider_id = next(iter(self._clients), None)
        if provider_id is None:
            raise KeyError(call_id)
        client = self._clients[provider_id]
        cancel = getattr(client, "cancel", None)
        if cancel is not None:
            await cancel(call_id)
        else:
            await client.request("cancel", {"call_id": call_id}, timeout=30)

    def remove(self, provider_id: str) -> None:
        self._processes.pop(provider_id, None)
        self._clients.pop(provider_id, None)
        target = self.root / provider_id
        if target.exists():
            shutil.rmtree(target)
