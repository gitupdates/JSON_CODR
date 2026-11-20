import tempfile
import unittest
from pathlib import Path

from web_app.core.rea_provider_state import ReaProviderStore, RevisionConflict


class ReaProviderStoreTests(unittest.TestCase):
    def test_candidate_transitions_require_expected_revision(self):
        with tempfile.TemporaryDirectory() as directory:
            store = ReaProviderStore(Path(directory) / "state.sqlite")
            candidate = store.discover("6.9.0", integrity="sha512-abc", source="https://registry.npmjs.org")

            staged = store.transition("6.9.0", "acquiring", expected_revision=candidate.revision)
            self.assertEqual(staged.revision, 1)
            with self.assertRaises(RevisionConflict):
                store.transition("6.9.0", "staged", expected_revision=0)
            store.close()

    def test_activation_is_compare_and_swap_and_lease_pins_old_version(self):
        with tempfile.TemporaryDirectory() as directory:
            store = ReaProviderStore(Path(directory) / "state.sqlite")
            for version in ("6.9.0", "6.10.0"):
                candidate = store.discover(version, integrity=f"sha512-{version}", source="https://registry.npmjs.org")
                for state in ("acquiring", "staged", "verifying", "ready"):
                    candidate = store.transition(version, state, expected_revision=candidate.revision)

            first = store.activate("6.9.0", expected_generation=0)
            lease = store.acquire_lease("task-1")
            second = store.activate("6.10.0", expected_generation=first.generation)

            self.assertEqual(lease.version, "6.9.0")
            self.assertEqual(second.generation, 2)
            self.assertEqual(store.lease_count("6.9.0"), 1)
            with self.assertRaises(RevisionConflict):
                store.activate("6.9.0", expected_generation=first.generation)
            store.release_lease(lease.lease_id)
            self.assertEqual(store.lease_count("6.9.0"), 0)
            store.close()

    def test_canary_rollback_only_applies_to_current_generation(self):
        with tempfile.TemporaryDirectory() as directory:
            store = ReaProviderStore(Path(directory) / "state.sqlite")
            for version in ("6.9.0", "6.10.0"):
                candidate = store.discover(version, integrity=f"sha512-{version}", source="https://registry.npmjs.org")
                for state in ("acquiring", "staged", "verifying", "ready"):
                    candidate = store.transition(version, state, expected_revision=candidate.revision)
            first = store.activate("6.9.0", expected_generation=0)
            second = store.activate("6.10.0", expected_generation=first.generation)

            rollback = store.record_canary_failure(second.generation, "protocol failure")
            self.assertEqual(rollback.version, "6.9.0")
            self.assertEqual(rollback.generation, 3)
            with self.assertRaises(RevisionConflict):
                store.record_canary_failure(second.generation, "stale failure")
            store.close()

    def test_recovery_quarantines_interrupted_candidates_without_changing_active(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "state.sqlite"
            store = ReaProviderStore(database)
            active = store.discover("6.9.0", integrity="sha512-good", source="https://registry.npmjs.org")
            for state in ("acquiring", "staged", "verifying", "ready"):
                active = store.transition("6.9.0", state, expected_revision=active.revision)
            store.activate("6.9.0", expected_generation=0)
            pending = store.discover("6.10.0", integrity="sha512-new", source="https://registry.npmjs.org")
            store.transition("6.10.0", "acquiring", expected_revision=pending.revision)
            store.close()

            reopened = ReaProviderStore(database)
            recovered = reopened.recover()
            self.assertEqual(recovered[0].state, "quarantined")
            self.assertEqual(reopened.active().version, "6.9.0")
            reopened.close()


if __name__ == "__main__":
    unittest.main()
