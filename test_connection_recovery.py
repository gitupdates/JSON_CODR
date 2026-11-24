import asyncio
import json
import tempfile
import unittest
from pathlib import Path


class _Adapter:
    def __init__(self, descriptor, status, plan, verified=None):
        self.descriptor = descriptor
        self.status = status
        self.recovery_plan = plan
        self.verified = verified or status
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.block_recovery = False
        self.action_detail = "repaired"

    async def describe(self):
        return self.descriptor

    async def probe(self):
        return self.status

    async def plan(self, status):
        return self.recovery_plan

    async def recover(self, action_ids):
        from web_app.core.connection_recovery import RecoveryActionResult

        self.started.set()
        if self.block_recovery:
            await self.release.wait()
        return tuple(
            RecoveryActionResult(action_id=action_id, status="completed", detail=self.action_detail)
            for action_id in sorted(action_ids)
        )

    async def verify(self):
        return self.verified

    async def preview(self, action_id):
        return {"action_id": action_id, "before": {"status": "degraded"}, "after": {"status": "ready"}}


class ConnectionRecoveryTests(unittest.IsolatedAsyncioTestCase):
    def _types(self):
        from web_app.core.connection_recovery import (
            ConnectionDescriptor,
            ConnectionRecoveryService,
            ConnectionState,
            ConnectionStatus,
            RecoveryAction,
            RecoveryActionClass,
            RecoveryInProgress,
            RecoveryPlan,
        )

        return {
            "descriptor": ConnectionDescriptor,
            "service": ConnectionRecoveryService,
            "state": ConnectionState,
            "status": ConnectionStatus,
            "action": RecoveryAction,
            "action_class": RecoveryActionClass,
            "in_progress": RecoveryInProgress,
            "plan": RecoveryPlan,
        }

    def _adapter(self, connection_id="ollama:default", display_name="Ollama", *, detail=None):
        types = self._types()
        descriptor = types["descriptor"](
            connection_id=connection_id,
            display_name=display_name,
            kind="ollama",
            credential_mode="native",
            capabilities=("inference",),
        )
        status = types["status"](
            connection_id=connection_id,
            state=types["state"].degraded,
            functional_probe=False,
            diagnostic_code="probe_failed",
            detail=detail,
        )
        plan = types["plan"](
            connection_id=connection_id,
            revision="plan-1",
            actions=(types["action"](
                action_id="repair-config",
                label="Repair configuration",
                action_class=types["action_class"].automatic,
            ),),
        )
        return _Adapter(descriptor, status, plan)

    async def test_inventory_is_deterministic_and_redacts_sensitive_diagnostics(self):
        types = self._types()
        first = self._adapter(
            "github:default",
            "GitHub",
            detail="ghp_abcdefghijklmnopqrstuvwxyz123456 at C:\\Users\\BLACK\\secret.txt",
        )
        second = self._adapter("ollama:default", "Ollama")
        service = types["service"]([second, first])

        inventory = await service.inventory()

        self.assertEqual([item.connection_id for item in inventory], ["github:default", "ollama:default"])
        self.assertNotIn("ghp_", inventory[0].detail)
        self.assertNotIn("BLACK", inventory[0].detail)
        self.assertIn("[redacted-token]", inventory[0].detail)
        self.assertIn("[redacted-user]", inventory[0].detail)

    async def test_recovery_requires_functional_verification_before_ready(self):
        types = self._types()
        adapter = self._adapter()
        adapter.verified = types["status"](
            connection_id="ollama:default",
            state=types["state"].ready,
            functional_probe=False,
            diagnostic_code="port_only",
        )
        service = types["service"]([adapter])
        result = await service.recover("ollama:default", frozenset({"repair-config"}))

        self.assertEqual(result.final_status.state, types["state"].degraded)
        self.assertFalse(result.final_status.functional_probe)

    async def test_recovery_requires_explicit_approval_and_redacts_action_output(self):
        types = self._types()
        adapter = self._adapter()
        adapter.recovery_plan = types["plan"](
            connection_id="ollama:default",
            revision="plan-2",
            actions=(types["action"](
                action_id="restart-owned-process",
                label="Restart owned process",
                action_class=types["action_class"].approval_required,
            ),),
        )
        service = types["service"]([adapter])
        adapter.action_detail = "ghp_abcdefghijklmnopqrstuvwxyz123456 at C:\\Users\\BLACK\\secret.txt"

        with self.assertRaisesRegex(PermissionError, "requires approval"):
            await service.recover("ollama:default", frozenset({"restart-owned-process"}))

        result = await service.recover(
            "ollama:default",
            frozenset({"restart-owned-process"}),
            approved_action_ids=frozenset({"restart-owned-process"}),
        )
        self.assertEqual(
            result.action_results[0].detail,
            "[redacted-token] at C:\\Users\\[redacted-user]\\secret.txt",
        )

    async def test_recovery_rejects_a_second_run_for_the_same_connection(self):
        types = self._types()
        adapter = self._adapter()
        adapter.block_recovery = True
        service = types["service"]([adapter])
        first = asyncio.create_task(service.recover("ollama:default", frozenset({"repair-config"})))
        await adapter.started.wait()

        with self.assertRaises(types["in_progress"]):
            await service.recover("ollama:default", frozenset({"repair-config"}))

        adapter.release.set()
        await first

    async def test_plan_uses_current_probe_and_rejects_unknown_actions(self):
        types = self._types()
        adapter = self._adapter()
        service = types["service"]([adapter])

        plan = await service.plan("ollama:default")

        self.assertEqual(plan.revision, "plan-1")
        with self.assertRaisesRegex(ValueError, "unknown recovery action"):
            await service.recover("ollama:default", frozenset({"not-in-plan"}))

    async def test_confirmed_recovery_is_action_bound_and_one_time(self):
        types = self._types()
        adapter = self._adapter()
        service = types["service"]([adapter])

        preview = await service.preview("ollama:default", "repair-config")
        result = await service.recover_confirmed(
            "ollama:default", "repair-config", preview["confirmation_code"],
        )

        self.assertEqual(result.action_results[0].status, "completed")
        with self.assertRaisesRegex(PermissionError, "confirmation"):
            await service.recover_confirmed(
                "ollama:default", "repair-config", preview["confirmation_code"],
            )


class ProgramConnectionAdapterTests(unittest.IsolatedAsyncioTestCase):
    def _adapter(self, root: Path, *, probe=True):
        try:
            from web_app.integrations.connection_adapters import FileConnectionAdapter, ProgramConnectionSpec
        except ImportError as error:
            self.fail(f"Program connection adapters are missing: {error}")
        config = root / "client" / "mcp.json"
        spec = ProgramConnectionSpec(
            connection_id="vscode:json-codr",
            display_name="VS Code / Copilot",
            kind="mcp",
            credential_mode="none",
            capabilities=("tools", "models"),
            config_paths=(config,),
            generated_config={"servers": {"json-codr": {"type": "http", "url": "http://127.0.0.1:8765/mcp"}}},
        )
        return FileConnectionAdapter(spec, functional_probe=lambda: probe), config

    async def test_scan_is_bounded_and_does_not_overwrite_malformed_configuration(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            adapter, config = self._adapter(root)
            config.parent.mkdir(parents=True)
            config.write_text('{"servers":', encoding="utf-8")
            decoy = root / "unbounded" / "deep" / "mcp.json"
            decoy.parent.mkdir(parents=True)
            decoy.write_text("{}", encoding="utf-8")

            status = await adapter.probe()

            self.assertEqual(status.diagnostic_code, "config_malformed")
            self.assertEqual(config.read_text(encoding="utf-8"), '{"servers":')
            self.assertNotIn(str(decoy), status.detail or "")

    async def test_preview_configure_backup_and_restore_are_reversible(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            adapter, config = self._adapter(root)
            config.parent.mkdir(parents=True)
            original = {"existing": True}
            config.write_text(json.dumps(original), encoding="utf-8")

            preview = await adapter.preview("configure")
            configured = await adapter.recover(frozenset({"configure"}))
            restored = await adapter.recover(frozenset({"restore"}))

            self.assertEqual(preview["target_name"], "mcp.json")
            self.assertEqual(preview["before"], {"status": "valid", "keys": ["existing"]})
            self.assertEqual(preview["after"], {"status": "generated", "keys": ["servers"]})
            self.assertEqual(configured[0].status, "completed")
            self.assertEqual(restored[0].status, "completed")
            self.assertEqual(json.loads(config.read_text(encoding="utf-8")), original)

    async def test_ready_requires_a_real_functional_probe(self):
        with tempfile.TemporaryDirectory() as temporary:
            adapter, config = self._adapter(Path(temporary), probe=False)
            config.parent.mkdir(parents=True)
            config.write_text(json.dumps(adapter.spec.generated_config), encoding="utf-8")

            status = await adapter.probe()

            self.assertFalse(status.functional_probe)
            self.assertEqual(status.diagnostic_code, "functional_probe_failed")

    async def test_factory_exposes_each_supported_program_without_unbounded_search(self):
        from web_app.integrations.connection_adapters import build_program_connection_adapters

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            adapters = build_program_connection_adapters(
                data_root=root / "data",
                home=root / "home",
                appdata=root / "appdata",
                localappdata=root / "localappdata",
                service_url="http://127.0.0.1:8765",
                functional_probe=lambda: False,
            )

        self.assertEqual(
            {adapter.descriptor.connection_id for adapter in adapters},
            {
                "claude:desktop", "codex:plugin", "cursor:global", "generic:mcp",
                "generic:openai", "ollama:native", "visualstudio:2022",
                "vscode:copilot", "windsurf:global",
            },
        )


if __name__ == "__main__":
    unittest.main()
