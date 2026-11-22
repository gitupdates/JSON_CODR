import asyncio
import unittest


class _Adapter:
    def __init__(self, descriptor, status, plan, verified=None):
        self.descriptor = descriptor
        self.status = status
        self.recovery_plan = plan
        self.verified = verified or status
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.block_recovery = False

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
            RecoveryActionResult(action_id=action_id, status="completed", detail="repaired")
            for action_id in sorted(action_ids)
        )

    async def verify(self):
        return self.verified


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


if __name__ == "__main__":
    unittest.main()
