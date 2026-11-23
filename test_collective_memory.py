import tempfile
import unittest
from pathlib import Path

from web_app.core.memory import MemoryDraft, MemoryPolicyError, MemoryStore


class CollectiveMemoryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.store = MemoryStore(Path(self.temporary.name) / "memory.sqlite")

    def tearDown(self):
        self.store.close()
        self.temporary.cleanup()

    def draft(self, **changes):
        values = {
            "user_id": "administrator",
            "project_id": "project-1",
            "thread_id": "thread-1",
            "task_id": "task-1",
            "kind": "verified_outcome",
            "content": "Focused tests passed after repairing the planner contract.",
            "source_refs": ("event:verification-1",),
            "idempotency_key": "task-1:verification-1",
        }
        values.update(changes)
        return MemoryDraft(**values)

    def test_accept_is_scoped_idempotent_and_searchable(self):
        first = self.store.accept(self.draft())
        second = self.store.accept(self.draft())

        self.assertEqual(first.memory_id, second.memory_id)
        self.assertEqual(
            self.store.search_collective("administrator", "project-1", "planner"),
            (first,),
        )
        self.assertEqual(self.store.search_collective("other-user", "project-1", "planner"), ())
        self.assertEqual(self.store.search_collective("administrator", "other-project", "planner"), ())

    def test_requires_evidence_and_rejects_likely_secrets(self):
        with self.assertRaisesRegex(MemoryPolicyError, "evidence"):
            self.store.accept(self.draft(source_refs=()))
        with self.assertRaisesRegex(MemoryPolicyError, "secret"):
            self.store.accept(
                self.draft(
                    content="GITHUB_TOKEN=ghp_abcdefghijklmnopqrstuvwxyz123456",
                    idempotency_key="secret-attempt",
                )
            )

    def test_detailed_retention_requires_explicit_opt_in(self):
        with self.assertRaisesRegex(MemoryPolicyError, "detailed retention"):
            self.store.accept(
                self.draft(
                    content="RAW TRANSCRIPT:\nuser: fix it\nassistant: internal output",
                    idempotency_key="raw-without-consent",
                )
            )

        record = self.store.accept(
            self.draft(
                content="RAW TRANSCRIPT:\nuser: fix it\nassistant: internal output",
                retain_details=True,
                idempotency_key="raw-with-consent",
            )
        )

        self.assertTrue(record.retain_details)

    def test_revoke_hides_record_from_active_search_but_preserves_export(self):
        record = self.store.accept(self.draft())

        revoked = self.store.revoke(
            record.memory_id,
            user_id="administrator",
            project_id="project-1",
            reason="outdated",
        )

        self.assertEqual(revoked.status, "revoked")
        self.assertEqual(self.store.search_collective("administrator", "project-1", "planner"), ())
        exported = self.store.export_collective("administrator", "project-1", include_inactive=True)
        self.assertEqual(exported[0].memory_id, record.memory_id)
        self.assertEqual(exported[0].status, "revoked")

    def test_supersede_links_old_and_new_records(self):
        old = self.store.accept(self.draft())
        new = self.store.supersede(
            old.memory_id,
            self.draft(
                content="Focused tests and live verification passed after repairing the planner contract.",
                source_refs=("event:verification-2",),
                idempotency_key="task-1:verification-2",
            ),
        )

        exported = self.store.export_collective("administrator", "project-1", include_inactive=True)
        old_export = next(item for item in exported if item.memory_id == old.memory_id)
        self.assertEqual(old_export.status, "superseded")
        self.assertEqual(old_export.superseded_by, new.memory_id)
        self.assertEqual(self.store.search_collective("administrator", "project-1", "live"), (new,))


if __name__ == "__main__":
    unittest.main()
