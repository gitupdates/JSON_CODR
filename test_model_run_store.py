import importlib
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from web_app.models import (
    CanonicalModelResult,
    ModelRunCreateRequest,
    ModelTiming,
    OriginalModelOutput,
)


class ModelRunStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        try:
            module = importlib.import_module("web_app.model_run_store")
        except ModuleNotFoundError:
            self.fail("missing web_app.model_run_store")
        self.module = module
        self.store = module.ModelRunStore(Path(self.temp.name))
        self.request = ModelRunCreateRequest(
            session_id="session-1",
            prompt="Review this",
            profile="general",
            request_key="request-1",
        )

    def tearDown(self):
        self.temp.cleanup()

    def result(self, model, status="completed"):
        return CanonicalModelResult(
            result_id=f"result-{model}",
            requested_model=model,
            effective_model=model,
            status=status,
            timing=ModelTiming(
                started_at=datetime(2026, 11, 17, tzinfo=timezone.utc),
                completed_at=datetime(2026, 11, 17, tzinfo=timezone.utc),
                duration_ms=10,
            ),
            original_output_id=f"original-{model}",
            original_output_digest="sha256:" + "1" * 64,
            summary="done",
            answer="answer",
        )

    def test_run_survives_restart_and_preserves_roster_order(self):
        created = self.store.create(self.request, ["model-b", "model-a"], "request-1")
        reopened = self.module.ModelRunStore(Path(self.temp.name)).get(created.run_id)
        self.assertEqual(reopened.roster, ["model-b", "model-a"])
        self.assertEqual([item.requested_model for item in reopened.results], ["model-b", "model-a"])
        self.assertEqual(reopened.status, "queued")

    def test_request_key_replays_same_request_and_conflicts_on_different_fingerprint(self):
        first = self.store.create(self.request, ["model-a"], "request-1")
        replay = self.store.create(self.request, ["model-a"], "request-1")
        self.assertEqual(replay.run_id, first.run_id)

        changed = self.request.model_copy(update={"prompt": "Different"})
        with self.assertRaises(self.module.RequestKeyConflict):
            self.store.create(changed, ["model-a"], "request-1")

    def test_original_output_is_content_addressed_and_restart_safe(self):
        run = self.store.create(self.request, ["model-a"], "request-1")
        original = OriginalModelOutput(
            output_id="original-a",
            model="model-a",
            content="unaltered",
            digest="sha256:" + "a" * 64,
        )
        self.store.append_original(run.run_id, "result-model-a", original)
        path = Path(self.temp.name) / "model-runs" / run.run_id / "originals" / ("a" * 64 + ".json")
        self.assertTrue(path.is_file())
        reopened = self.module.ModelRunStore(Path(self.temp.name))
        self.assertEqual(reopened.get_original(run.run_id, "result-model-a"), original)

    def test_status_aggregation_and_cancellation_preserve_committed_completion(self):
        run = self.store.create(self.request, ["model-a", "model-b"], "request-1")
        self.store.update_result(run.run_id, self.result("model-a"))
        partial_running = self.store.get(run.run_id)
        self.assertEqual(partial_running.status, "running")

        cancelled = self.store.request_cancel(run.run_id)
        self.assertEqual(cancelled.status, "partial")
        by_model = {item.requested_model: item for item in cancelled.results}
        self.assertEqual(by_model["model-a"].status, "completed")
        self.assertEqual(by_model["model-b"].status, "cancelled")

        ignored = self.store.update_result(run.run_id, self.result("model-b"))
        self.assertEqual({item.requested_model: item.status for item in ignored.results}["model-b"], "cancelled")

    def test_terminal_failures_aggregate_and_session_delete_removes_runs(self):
        run = self.store.create(self.request, ["model-a", "model-b"], "request-1")
        self.store.update_result(run.run_id, self.result("model-a", "failed"))
        failed = self.store.update_result(run.run_id, self.result("model-b", "timeout"))
        self.assertEqual(failed.status, "failed")

        self.store.delete_session("session-1")
        with self.assertRaises(KeyError):
            self.store.get(run.run_id)


if __name__ == "__main__":
    unittest.main()
