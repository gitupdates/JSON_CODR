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

    def test_reconciliation_revokes_invalid_active_projection_without_dropping_valid_record(self):
        valid = self.store.accept(self.draft(
            task_id="a" * 32,
            kind="previous_session_history",
            content="Title: Valid parser history\nKeywords: valid-parser-token",
            source_refs=("previous-session:" + "a" * 32,),
            idempotency_key="previous-session:" + "a" * 32,
        ))
        orphan = self.store.accept(self.draft(
            task_id="b" * 32,
            kind="previous_session_history",
            content="Title: Orphan parser history\nKeywords: orphan-parser-token",
            source_refs=("previous-session:" + "b" * 32,),
            idempotency_key="previous-session:" + "b" * 32,
        ))

        revoked = self.store.reconcile_collective(
            "previous_session_history",
            lambda record: record.memory_id == valid.memory_id,
            reason="authoritative snapshot is unavailable",
        )

        self.assertEqual(revoked, (orphan.memory_id,))
        self.assertEqual(
            self.store.search_collective(
                "administrator", "project-1", "valid parser token",
                kind="previous_session_history",
            ),
            (valid,),
        )
        self.assertEqual(
            self.store.search_collective(
                "administrator", "project-1", "orphan parser token",
                kind="previous_session_history",
            ),
            (),
        )

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

    def test_safe_kind_filtered_search_is_scoped_active_and_bounded(self):
        history = self.store.accept(self.draft(
            kind="previous_session_history",
            content="file:src/widget.py component:parser model:qwen task:repair user-keyword",
            source_refs=("previous-session:" + "a" * 32,),
            idempotency_key="previous-session:" + "a" * 32,
        ))
        self.store.accept(self.draft(
            kind="verified_outcome",
            content="file:src/widget.py component:parser",
            idempotency_key="wrong-kind",
        ))
        inactive = self.store.accept(self.draft(
            kind="previous_session_history",
            content="file:src/widget.py inactive",
            idempotency_key="inactive-history",
        ))
        self.store.revoke(
            inactive.memory_id,
            user_id="administrator",
            project_id="project-1",
            reason="inactive",
        )

        for query in ("src/widget.py", "component:parser", "model:qwen", "task:repair", "user-keyword"):
            self.assertEqual(
                self.store.search_collective(
                    "administrator", "project-1", query,
                    kind="previous_session_history", limit=500,
                ),
                (history,),
            )
        self.assertEqual(
            self.store.search_collective(
                "administrator", "project-1", "widget",
                kind="verified_outcome",
            )[0].kind,
            "verified_outcome",
        )
        self.assertEqual(
            self.store.search_collective(
                "other", "project-1", "widget", kind="previous_session_history"
            ),
            (),
        )
        self.assertEqual(
            self.store.search_collective(
                "administrator", "other", "widget", kind="previous_session_history"
            ),
            (),
        )

    def test_search_normalizes_fts_operators_and_punctuation_without_raising(self):
        self.store.accept(self.draft(
            kind="previous_session_history",
            content="parser repair completed",
            idempotency_key="safe-search",
        ))

        for query in ('"', "***", "NEAR(", "parser OR", "parser) (repair", "-", ":"):
            with self.subTest(query=query):
                result = self.store.search_collective(
                    "administrator", "project-1", query,
                    kind="previous_session_history", limit=10_000,
                )
                self.assertIsInstance(result, tuple)
                self.assertLessEqual(len(result), 50)

    def test_malformed_fts_and_broad_common_words_do_not_return_irrelevant_history(self):
        relevant = self.store.accept(self.draft(
            kind="previous_session_history",
            content="Title: Billing migration\nKeywords: component:invoice task:billing-migration",
            source_refs=("previous-session:" + "a" * 32,),
            idempotency_key="billing-history",
        ))
        self.store.accept(self.draft(
            kind="previous_session_history",
            content="Title: Weather deployment\nPlease explain the weather deployment checklist",
            source_refs=("previous-session:" + "b" * 32,),
            idempotency_key="weather-history",
        ))

        self.assertEqual(
            self.store.search_collective(
                "administrator", "project-1", "NEAR(", kind="previous_session_history"
            ),
            (),
        )
        self.assertEqual(
            self.store.search_collective(
                "administrator", "project-1", "Please explain billing migration",
                kind="previous_session_history",
            ),
            (relevant,),
        )

    def test_verbose_prompt_keeps_strong_parser_token_repair_phrase_relevant(self):
        history = self.store.accept(self.draft(
            kind="previous_session_history",
            content=(
                "Title: Parser token repair\n"
                "Keywords: component:parser task:token-repair model:qwen-coder"
            ),
            source_refs=("previous-session:" + "c" * 32,),
            idempotency_key="parser-token-repair-history",
        ))
        self.store.accept(self.draft(
            kind="previous_session_history",
            content=(
                "Title: Travel preferences\n"
                "Summary: New release expected behavior was mentioned incidentally."
            ),
            source_refs=("previous-session:" + "d" * 32,),
            idempotency_key="incidental-travel-history",
        ))

        verbose = (
            "Please revisit the parser token repair while planning new release regression "
            "validation and explain expected behavior"
        )
        unrelated = (
            "Please revisit release planning regression validation and explain expected behavior"
        )

        self.assertEqual(
            self.store.search_collective(
                "administrator", "project-1", verbose,
                kind="previous_session_history",
            ),
            (history,),
        )
        self.assertEqual(
            self.store.search_collective(
                "administrator", "project-1", "token repair",
                kind="previous_session_history",
            ),
            (history,),
        )
        self.assertEqual(
            self.store.search_collective(
                "administrator", "project-1", unrelated,
                kind="previous_session_history",
            ),
            (),
        )
        self.assertEqual(
            self.store.search_collective(
                "administrator", "project-1", "parser NEAR(",
                kind="previous_session_history",
            ),
            (),
        )


if __name__ == "__main__":
    unittest.main()
