import errno
import io
import json
import os
import tempfile
import threading
import unittest
from contextlib import contextmanager
from unittest.mock import patch
from pathlib import Path

from web_app.attachments import AttachmentService
from web_app.core.memory import MemoryDraft, MemoryStore
from web_app.core.project_registry import ProjectRegistry
from web_app.models import ChatMessage, ExtractionState, ObjectReference, ProjectSessionSaveRequest, ReasoningEntry, ReasoningTrace
from web_app.project_sessions import ProjectSessionService
from web_app.workspace import WorkspaceService


class ProjectSessionServiceTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)
        self.project_root = self.root / "registered-project"
        self.project_root.mkdir()
        self.registry = ProjectRegistry(self.root / "projects.sqlite")
        self.project = self.registry.register(self.project_root)
        self.workspace = WorkspaceService(self.root / "data")
        self.attachments = AttachmentService(self.workspace)
        self.sessions = ProjectSessionService(self.workspace, self.registry)

    def tearDown(self):
        self.registry.close()
        self.temporary_directory.cleanup()

    def _live_session(self):
        session = self.workspace.create_session("owner-1", self.project.project_id)
        self.workspace.append_message(session.id, ChatMessage(
            role="user", content="Implement parser.py and verify the model output.",
            references=[ObjectReference(id="ref-1", kind="project_file", label="parser.py", target="parser.py")],
        ))
        self.workspace.append_message(session.id, ChatMessage(
            role="assistant", content="Parser implementation completed.", effective_model="local:model",
            reasoning=ReasoningTrace(entries=[ReasoningEntry(
                sequence=0, kind="analysis", text="private chain must never be summarized", provenance="native_provider",
            )]),
        ))
        self.attachments.import_stream(session.id, "notes.txt", io.BytesIO(b"attachment text"))
        artifacts = self.workspace.sessions_root / session.id / "artifacts"
        artifacts.mkdir()
        (artifacts / "result.md").write_text("artifact", encoding="utf-8")
        return session

    @staticmethod
    def _run_worker(output, operation):
        try:
            output["result"] = operation()
        except BaseException as error:
            output["error"] = error

    @staticmethod
    def _attachment_state(directory):
        manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
        files = {}
        for tree_name in ("originals", "extracted"):
            tree = directory / tree_name
            if tree.is_dir():
                files[tree_name] = {
                    path.name: path.read_bytes()
                    for path in sorted(tree.iterdir(), key=lambda item: item.name)
                    if path.is_file()
                }
            else:
                files[tree_name] = {}
        return {"attachments": manifest["attachments"], "files": files}

    def _assert_no_staging(self):
        root = self.sessions.project_directory(self.project.project_id) / "sessions"
        self.assertFalse(
            root.exists() and any(path.name.startswith(".staging-") for path in root.iterdir())
        )

    def test_save_creates_immutable_project_scoped_copy_with_bounded_safe_summary(self):
        session = self._live_session()

        snapshot = self.sessions.save(session.id, self.project.project_id, "owner-1", "Parser fix", "fix", ["Urgent", "parser"])
        snapshot_dir = self.sessions.snapshot_directory(snapshot.id, self.project.project_id)
        manifest = self.workspace.get_session(session.id)

        self.assertEqual(snapshot.project_id, self.project.project_id)
        self.assertEqual(snapshot.owner_user_id, "owner-1")
        self.assertEqual(snapshot.source_session_id, session.id)
        self.assertTrue((snapshot_dir / "manifest.json").is_file())
        self.assertTrue((snapshot_dir / "originals").is_dir())
        self.assertTrue((snapshot_dir / "extracted").is_dir())
        self.assertTrue((snapshot_dir / "artifacts" / "result.md").is_file())
        self.assertIn("parser.py", snapshot.summary)
        self.assertNotIn("private chain", snapshot.summary)
        self.assertLessEqual(len(snapshot.summary), 8_000)
        self.assertIn("snapshot:" + snapshot.id, snapshot.keywords)
        self.assertIn("project:" + self.project.project_id, snapshot.keywords)
        self.assertIn("file:parser.py", snapshot.keywords)
        self.assertEqual(manifest.messages[0].content, "Implement parser.py and verify the model output.")

    def test_repeated_saves_are_distinct_and_restore_creates_owner_bound_new_session(self):
        session = self._live_session()
        first = self.sessions.save(session.id, self.project.project_id, "owner-1", "Parser fix", "fix", [])
        second = self.sessions.save(session.id, self.project.project_id, "owner-1", "Parser fix", "fix", [])

        restored = self.sessions.restore(first.id, self.project.project_id, "owner-1")
        live = self.workspace.get_session(restored.session_id)

        self.assertNotEqual(first.id, second.id)
        self.assertNotEqual(restored.session_id, session.id)
        self.assertEqual(live.owner_user_id, "owner-1")
        self.assertEqual(live.project_id, self.project.project_id)
        self.assertEqual([m.content for m in live.messages], [m.content for m in self.workspace.get_session(session.id).messages])
        self.assertEqual(len(live.attachments), 1)
        self.assertEqual((self.workspace.sessions_root / restored.session_id / "artifacts" / "result.md").read_text(encoding="utf-8"), "artifact")

    def test_save_projects_compact_history_with_scoped_idempotent_metadata(self):
        memory = MemoryStore(self.root / "memory.sqlite")
        try:
            sessions = ProjectSessionService(self.workspace, self.registry, memory=memory)
            session = self._live_session()

            snapshot = sessions.save(
                session.id,
                self.project.project_id,
                "owner-1",
                "Parser compatibility",
                "fix",
                ["component:parser", "file:parser.py", "user-search-term"],
            )

            records = memory.search_collective(
                "owner-1",
                self.project.project_id,
                "parser.py",
                kind="previous_session_history",
            )
            self.assertEqual(len(records), 1)
            record = records[0]
            self.assertEqual(record.kind, "previous_session_history")
            self.assertEqual(record.thread_id, session.id)
            self.assertEqual(record.task_id, snapshot.id)
            self.assertEqual(record.source_refs, (f"previous-session:{snapshot.id}",))
            self.assertFalse(record.retain_details)
            self.assertEqual(record.idempotency_key, f"previous-session:{snapshot.id}")
            self.assertLessEqual(len(record.content), 65_536)
            self.assertEqual(snapshot.indexing_status, "indexed")
            self.assertEqual(snapshot.indexed_memory_id, record.memory_id)
            stored = sessions.get(snapshot.id, self.project.project_id, "owner-1")
            self.assertEqual(stored.indexing_status, "indexed")
            self.assertEqual(stored.indexed_memory_id, record.memory_id)
            replay = memory.accept(MemoryDraft(
                user_id="owner-1",
                project_id=self.project.project_id,
                thread_id=session.id,
                task_id=snapshot.id,
                kind="previous_session_history",
                content=record.content,
                source_refs=(f"previous-session:{snapshot.id}",),
                retain_details=False,
                idempotency_key=f"previous-session:{snapshot.id}",
            ))
            self.assertEqual(replay.memory_id, record.memory_id)
        finally:
            memory.close()

    def test_live_memory_disable_skips_projection_without_losing_snapshot(self):
        memory = MemoryStore(self.root / "live-policy-memory.sqlite")
        enabled = {"value": False}
        try:
            sessions = ProjectSessionService(
                self.workspace,
                self.registry,
                memory=memory,
                memory_enabled=lambda: enabled["value"],
            )
            session = self._live_session()

            disabled = sessions.save(
                session.id, self.project.project_id, "owner-1", "Disabled memory", "fix", []
            )
            self.assertEqual(disabled.indexing_status, "skipped")
            self.assertEqual(
                memory.export_collective("owner-1", self.project.project_id),
                (),
            )

            enabled["value"] = True
            indexed = sessions.save(
                session.id, self.project.project_id, "owner-1", "Enabled memory", "fix", []
            )
            self.assertEqual(indexed.indexing_status, "indexed")
            self.assertEqual(
                len(memory.export_collective("owner-1", self.project.project_id)),
                1,
            )
        finally:
            memory.close()

    def test_indexing_rejection_or_unavailability_never_loses_promoted_snapshot(self):
        class RejectingMemory:
            def accept(self, draft):
                raise ValueError("policy rejected")

        session = self._live_session()
        rejected_service = ProjectSessionService(self.workspace, self.registry, memory=RejectingMemory())
        rejected = rejected_service.save(
            session.id, self.project.project_id, "owner-1", "Rejected projection", "fix", []
        )
        self.assertEqual(rejected.indexing_status, "rejected")
        self.assertIsNone(rejected.indexed_memory_id)
        self.assertEqual(
            rejected_service.get(rejected.id, self.project.project_id, "owner-1").id,
            rejected.id,
        )

        memory = MemoryStore(self.root / "closed-memory.sqlite")
        memory.close()
        closed_service = ProjectSessionService(self.workspace, self.registry, memory=memory)
        closed = closed_service.save(
            session.id, self.project.project_id, "owner-1", "Closed projection", "fix", []
        )
        self.assertEqual(closed.indexing_status, "skipped")
        self.assertEqual(
            closed_service.get(closed.id, self.project.project_id, "owner-1").id,
            closed.id,
        )

    def test_promotion_failure_revokes_prepared_projection_best_effort(self):
        memory = MemoryStore(self.root / "rollback-memory.sqlite")
        try:
            sessions = ProjectSessionService(self.workspace, self.registry, memory=memory)
            session = self._live_session()
            with patch.object(sessions, "_promote_staging", side_effect=OSError("promotion failed")):
                with self.assertRaisesRegex(OSError, "promotion failed"):
                    sessions.save(
                        session.id, self.project.project_id, "owner-1", "Rollback projection", "fix", []
                    )
            exported = memory.export_collective(
                "owner-1", self.project.project_id, include_inactive=True
            )
            self.assertEqual(len(exported), 1)
            self.assertEqual(exported[0].status, "revoked")
            self.assertEqual(sessions.list(self.project.project_id, "owner-1"), [])
        finally:
            memory.close()

    def test_process_interruption_projection_is_revoked_during_restart_reconciliation(self):
        class SimulatedProcessInterruption(BaseException):
            pass

        memory_path = self.root / "interrupted-promotion-memory.sqlite"
        memory = MemoryStore(memory_path)
        session = self._live_session()
        sessions = ProjectSessionService(self.workspace, self.registry, memory=memory)
        try:
            with patch.object(
                sessions,
                "_promote_staging",
                side_effect=SimulatedProcessInterruption("process terminated"),
            ):
                with self.assertRaisesRegex(SimulatedProcessInterruption, "process terminated"):
                    sessions.save(
                        session.id,
                        self.project.project_id,
                        "owner-1",
                        "Interrupted parser projection",
                        "fix",
                        ["orphan-parser-token"],
                    )
            active_before_restart = memory.search_collective(
                "owner-1",
                self.project.project_id,
                "orphan parser token",
                kind="previous_session_history",
            )
            self.assertEqual(len(active_before_restart), 1)
        finally:
            memory.close()

        restarted_memory = MemoryStore(memory_path)
        try:
            restarted_sessions = ProjectSessionService(
                self.workspace, self.registry, memory=restarted_memory
            )
            self.assertEqual(
                restarted_memory.search_collective(
                    "owner-1",
                    self.project.project_id,
                    "orphan parser token",
                    kind="previous_session_history",
                ),
                (),
            )
            inactive = restarted_memory.export_collective(
                "owner-1", self.project.project_id, include_inactive=True
            )
            self.assertEqual(len(inactive), 1)
            self.assertEqual(inactive[0].status, "revoked")
            self.assertEqual(
                restarted_sessions.list(self.project.project_id, "owner-1"),
                [],
            )
        finally:
            restarted_memory.close()

    def test_concurrent_projection_validation_waits_for_promotion_and_keeps_indexed_record_active(self):
        memory = MemoryStore(self.root / "projection-overlap-memory.sqlite")
        sessions = ProjectSessionService(self.workspace, self.registry, memory=memory)
        session = self._live_session()
        accepted = threading.Event()
        release_promotion = threading.Event()
        accepted_record = {}
        original_project_history = sessions._project_history

        def pause_after_acceptance(snapshot, content):
            projected_snapshot, record = original_project_history(snapshot, content)
            accepted_record["record"] = record
            accepted.set()
            self.assertTrue(release_promotion.wait(3))
            return projected_snapshot, record

        save_result, filter_result, reconcile_result = {}, {}, {}
        save_thread = threading.Thread(
            target=self._run_worker,
            args=(save_result, lambda: sessions.save(
                session.id,
                self.project.project_id,
                "owner-1",
                "Concurrent parser projection",
                "fix",
                ["concurrent-parser-token"],
            )),
        )
        try:
            with patch.object(
                sessions, "_project_history", side_effect=pause_after_acceptance
            ):
                save_thread.start()
                self.assertTrue(accepted.wait(1))
                record = accepted_record["record"]
                self.assertIsNotNone(record)
                candidates = memory.search_collective(
                    "owner-1",
                    self.project.project_id,
                    "concurrent parser token",
                    kind="previous_session_history",
                )
                self.assertEqual([item.memory_id for item in candidates], [record.memory_id])

                filter_thread = threading.Thread(
                    target=self._run_worker,
                    args=(
                        filter_result,
                        lambda: sessions.filter_history_projections(candidates),
                    ),
                )
                reconcile_thread = threading.Thread(
                    target=self._run_worker,
                    args=(
                        reconcile_result,
                        lambda: ProjectSessionService(
                            self.workspace, self.registry, memory=memory
                        ),
                    ),
                )
                filter_thread.start()
                reconcile_thread.start()
                filter_thread.join(0.25)
                reconcile_thread.join(0.25)
                release_promotion.set()
                save_thread.join(3)
                filter_thread.join(3)
                reconcile_thread.join(3)

            self.assertFalse(save_thread.is_alive())
            self.assertFalse(filter_thread.is_alive())
            self.assertFalse(reconcile_thread.is_alive())
            self.assertNotIn("error", save_result)
            self.assertNotIn("error", filter_result)
            self.assertNotIn("error", reconcile_result)
            saved = save_result["result"]
            persisted = sessions.get(saved.id, self.project.project_id, "owner-1")
            self.assertEqual(saved.indexing_status, "indexed")
            self.assertEqual(persisted.indexing_status, "indexed")
            self.assertEqual(saved.indexed_memory_id, record.memory_id)
            self.assertEqual(persisted.indexed_memory_id, record.memory_id)
            active = memory.search_collective(
                "owner-1",
                self.project.project_id,
                "concurrent parser token",
                kind="previous_session_history",
            )
            self.assertEqual([item.memory_id for item in active], [record.memory_id])
            self.assertEqual(active[0].status, "active")
            self.assertEqual(
                [item.memory_id for item in filter_result["result"]],
                [record.memory_id],
            )
        finally:
            release_promotion.set()
            save_thread.join(3)
            memory.close()

    def test_post_promotion_downgrade_rejects_final_root_swap_without_external_write(self):
        memory = MemoryStore(self.root / "projection-downgrade-swap-memory.sqlite")
        external = self.root / "external-projection-downgrade"
        external.mkdir()
        sentinel = external / "sentinel.txt"
        sentinel.write_text("external data", encoding="utf-8")

        class SwapAtDowngradeWrite(ProjectSessionService):
            attacked = False
            final = None
            parked = None

            @contextmanager
            def _open_projection_rewrite_destination(
                swap_self, directory, pinned_directory, name
            ):
                swap_self.attacked = True
                swap_self.final = directory
                swap_self.parked = directory.with_name(f".{directory.name}.parked")
                directory.replace(swap_self.parked)
                os.symlink(external, directory, target_is_directory=True)
                with super()._open_projection_rewrite_destination(
                    directory, pinned_directory, name
                ) as destination:
                    yield destination

        sessions = SwapAtDowngradeWrite(self.workspace, self.registry, memory=memory)
        session = self._live_session()
        try:
            with patch.object(sessions, "valid_history_projection", return_value=False):
                with self.assertRaises((OSError, ValueError)):
                    sessions.save(
                        session.id,
                        self.project.project_id,
                        "owner-1",
                        "Downgrade root swap",
                        "fix",
                        ["downgrade-root-swap-token"],
                    )

            self.assertTrue(sessions.attacked)
            self.assertEqual("external data", sentinel.read_text(encoding="utf-8"))
            self.assertEqual([sentinel], list(external.iterdir()))
            self.assertIsNotNone(sessions.final)
            self.assertFalse(sessions.final.is_symlink())

            records = memory.export_collective(
                "owner-1", self.project.project_id, include_inactive=True
            )
            self.assertEqual(len(records), 1)
            self.assertEqual(records[0].status, "revoked")
            self.assertFalse(sessions.valid_history_projection(records[0]))

            retained = sessions.final if sessions.final.is_dir() else sessions.parked
            self.assertIsNotNone(retained)
            self.assertTrue(retained.is_dir())
            payload = json.loads((retained / "snapshot.json").read_text(encoding="utf-8"))
            expected_status = "indexed" if retained == sessions.final else "skipped"
            self.assertEqual(payload["snapshot"]["indexing_status"], expected_status)
            self.assertFalse(any(path.is_symlink() for path in retained.parent.iterdir()))
            self.assertFalse(
                any(path.name.startswith(".snapshot-") for path in retained.iterdir())
            )
        finally:
            for candidate in (sessions.final, sessions.parked):
                if candidate is not None:
                    sessions._remove_tree_no_follow(candidate)
            memory.close()

    def test_owner_and_project_boundaries_deny_snapshot_access(self):
        session = self._live_session()
        snapshot = self.sessions.save(session.id, self.project.project_id, "owner-1", "Parser fix", "fix", [])
        other_root = self.root / "other-project"
        other_root.mkdir()
        other = self.registry.register(other_root)

        with self.assertRaises(KeyError):
            self.sessions.get(snapshot.id, self.project.project_id, "owner-2")
        with self.assertRaises(KeyError):
            self.sessions.restore(snapshot.id, other.project_id, "owner-1")

    def test_save_promotes_same_owner_unassigned_session_to_project_once(self):
        session = self.workspace.create_session("owner-1", None)
        self.workspace.append_message(session.id, ChatMessage(role="user", content="Promote this work"))

        snapshot = self.sessions.save(
            session.id, self.project.project_id, "owner-1", "Promoted session", "feature", ["promotion"]
        )

        promoted = self.workspace.get_session(session.id)
        self.assertEqual(promoted.owner_user_id, "owner-1")
        self.assertEqual(promoted.project_id, self.project.project_id)
        self.assertEqual(snapshot.source_session_id, session.id)

        other_root = self.root / "promotion-other-project"
        other_root.mkdir()
        other = self.registry.register(other_root)
        with self.assertRaises(PermissionError):
            self.sessions.save(session.id, other.project_id, "owner-1", "Move again", "fix", [])

    def test_save_refuses_ownerless_or_foreign_unassigned_session_promotion(self):
        ownerless = self.workspace.create_session()
        foreign = self.workspace.create_session("owner-2", None)

        with self.assertRaises(PermissionError):
            self.sessions.save(ownerless.id, self.project.project_id, "owner-1", "Ownerless", "fix", [])
        with self.assertRaises(PermissionError):
            self.sessions.save(foreign.id, self.project.project_id, "owner-1", "Foreign", "fix", [])

    def test_failed_save_rolls_back_new_unassigned_project_binding(self):
        invalid = self.workspace.create_session("owner-1", None)
        with self.assertRaises(ValueError):
            self.sessions.save(invalid.id, self.project.project_id, "owner-1", "   ", "fix", [])
        self.assertIsNone(self.workspace.get_session(invalid.id).project_id)

        failed = self.workspace.create_session("owner-1", None)
        with patch.object(self.sessions, "_promote_staging", side_effect=OSError("promotion failed")):
            with self.assertRaisesRegex(OSError, "promotion failed"):
                self.sessions.save(
                    failed.id, self.project.project_id, "owner-1", "Failed promotion", "fix", []
                )
        self.assertIsNone(self.workspace.get_session(failed.id).project_id)

    def test_history_read_rejects_missing_tampered_and_linked_snapshot_content(self):
        session = self._live_session()
        snapshot = self.sessions.save(session.id, self.project.project_id, "owner-1", "Parser fix", "fix", [])
        history = self.sessions.snapshot_directory(snapshot.id, self.project.project_id) / "previous-session-history.md"

        self.assertIn("Parser fix", self.sessions.history(snapshot.id, self.project.project_id, "owner-1"))
        history.write_text("tampered", encoding="utf-8")
        with self.assertRaises(ValueError):
            self.sessions.history(snapshot.id, self.project.project_id, "owner-1")
        history.unlink()
        with self.assertRaises(ValueError):
            self.sessions.history(snapshot.id, self.project.project_id, "owner-1")
        with self.assertRaises(PermissionError):
            self.sessions.save(session.id, self.project.project_id, "owner-2", "Parser fix", "fix", [])

    def test_exact_prior_format_snapshot_restores_and_derives_canonical_history(self):
        session = self._live_session()
        snapshot = self.sessions.save(session.id, self.project.project_id, "owner-1", "Parser fix", "fix", [])
        directory = self.sessions.snapshot_directory(snapshot.id, self.project.project_id)
        manifest = directory / "snapshot.json"
        payload = json.loads(manifest.read_text(encoding="utf-8"))
        self.assertEqual(payload.get("history_digest_version"), 1)
        payload.pop("history_digest_version")
        payload["tree_digests"].pop("previous-session-history.md")
        manifest.write_text(json.dumps(payload), encoding="utf-8")

        history = self.sessions.history(snapshot.id, self.project.project_id, "owner-1")
        restored = self.sessions.restore(snapshot.id, self.project.project_id, "owner-1")

        self.assertIn("Title: Parser fix", history)
        self.assertEqual(self.workspace.get_session(restored.session_id).project_id, self.project.project_id)

    def test_legacy_restore_rejects_invalid_history_before_session_allocation(self):
        session = self._live_session()
        snapshot = self.sessions.save(session.id, self.project.project_id, "owner-1", "Parser fix", "fix", [])
        directory = self.sessions.snapshot_directory(snapshot.id, self.project.project_id)
        manifest = directory / "snapshot.json"
        payload = json.loads(manifest.read_text(encoding="utf-8"))
        self.assertEqual(payload.get("history_digest_version"), 1)
        payload.pop("history_digest_version")
        payload["tree_digests"].pop("previous-session-history.md")
        manifest.write_text(json.dumps(payload), encoding="utf-8")
        history = directory / "previous-session-history.md"

        for invalid_history in ("tampered", None):
            with self.subTest(invalid_history=invalid_history):
                if invalid_history is None:
                    history.unlink()
                else:
                    history.write_text(invalid_history, encoding="utf-8")
                before = {path.name for path in self.workspace.sessions_root.iterdir()}
                with self.assertRaises(ValueError):
                    self.sessions.restore(snapshot.id, self.project.project_id, "owner-1")
                self.assertEqual({path.name for path in self.workspace.sessions_root.iterdir()}, before)
                if invalid_history is not None:
                    history.write_text(self.sessions._history_markdown(snapshot), encoding="utf-8")

    def test_legacy_restore_rejects_linked_history_before_session_allocation(self):
        session = self._live_session()
        snapshot = self.sessions.save(session.id, self.project.project_id, "owner-1", "Parser fix", "fix", [])
        directory = self.sessions.snapshot_directory(snapshot.id, self.project.project_id)
        manifest = directory / "snapshot.json"
        payload = json.loads(manifest.read_text(encoding="utf-8"))
        self.assertEqual(payload.get("history_digest_version"), 1)
        payload.pop("history_digest_version")
        payload["tree_digests"].pop("previous-session-history.md")
        manifest.write_text(json.dumps(payload), encoding="utf-8")
        history = directory / "previous-session-history.md"
        external = self.root / "external-history.md"
        external.write_text(self.sessions._history_markdown(snapshot), encoding="utf-8")
        history.unlink()
        os.symlink(external, history)

        before = {path.name for path in self.workspace.sessions_root.iterdir()}
        with self.assertRaises(ValueError):
            self.sessions.restore(snapshot.id, self.project.project_id, "owner-1")
        self.assertEqual({path.name for path in self.workspace.sessions_root.iterdir()}, before)

    def test_modern_snapshot_without_required_history_digest_rejects_before_session_allocation(self):
        session = self._live_session()
        snapshot = self.sessions.save(session.id, self.project.project_id, "owner-1", "Parser fix", "fix", [])
        directory = self.sessions.snapshot_directory(snapshot.id, self.project.project_id)
        manifest = directory / "snapshot.json"
        payload = json.loads(manifest.read_text(encoding="utf-8"))
        self.assertEqual(payload.get("history_digest_version"), 1)
        payload["tree_digests"].pop("previous-session-history.md")
        manifest.write_text(json.dumps(payload), encoding="utf-8")

        before = {path.name for path in self.workspace.sessions_root.iterdir()}
        with self.assertRaises(ValueError):
            self.sessions.history(snapshot.id, self.project.project_id, "owner-1")
        with self.assertRaises(ValueError):
            self.sessions.restore(snapshot.id, self.project.project_id, "owner-1")
        self.assertEqual({path.name for path in self.workspace.sessions_root.iterdir()}, before)

    def test_unsafe_or_partial_allowed_source_rejects_save_and_cleans_staging(self):
        session = self._live_session()
        attachment = self.workspace.get_session(session.id).attachments[0]
        (self.workspace.sessions_root / session.id / "originals" / attachment.storage_name).unlink()

        with self.assertRaises(ValueError):
            self.sessions.save(session.id, self.project.project_id, "owner-1", "Parser fix", "fix", [])

        staging = self.sessions.project_directory(self.project.project_id) / ".staging"
        self.assertFalse(staging.exists() and any(staging.iterdir()))

    def test_restore_rolls_back_new_live_session_when_snapshot_copy_fails(self):
        session = self._live_session()
        snapshot = self.sessions.save(session.id, self.project.project_id, "owner-1", "Parser fix", "fix", [])
        source = self.sessions.snapshot_directory(snapshot.id, self.project.project_id) / "originals"
        for path in source.iterdir():
            path.unlink()

        before = {path.name for path in self.workspace.sessions_root.iterdir()}
        with self.assertRaises(ValueError):
            self.sessions.restore(snapshot.id, self.project.project_id, "owner-1")
        self.assertEqual({path.name for path in self.workspace.sessions_root.iterdir()}, before)

    def test_save_rejects_missing_or_traversal_attachment_storage_names(self):
        session = self._live_session()
        manifest = self.workspace.get_session(session.id)
        manifest.attachments[0].storage_name = "../../outside"
        self.workspace.save_manifest(manifest)

        with self.assertRaises(ValueError):
            self.sessions.save(session.id, self.project.project_id, "owner-1", "Parser fix", "fix", [])

        manifest.attachments[0].storage_name = None
        self.workspace.save_manifest(manifest)
        with self.assertRaises(ValueError):
            self.sessions.save(session.id, self.project.project_id, "owner-1", "Parser fix", "fix", [])

    def test_snapshot_manifest_and_restore_exclude_private_reasoning_and_inflight_state(self):
        session = self._live_session()
        self.workspace.append_message(session.id, ChatMessage(role="assistant", content="still running", status="streaming", task_id="live-task"))

        snapshot = self.sessions.save(session.id, self.project.project_id, "owner-1", "Parser fix", "fix", [])
        stored = json.loads((self.sessions.snapshot_directory(snapshot.id, self.project.project_id) / "manifest.json").read_text(encoding="utf-8"))
        restored = self.workspace.get_session(self.sessions.restore(snapshot.id, self.project.project_id, "owner-1").session_id)

        self.assertEqual(len(stored["messages"]), 2)
        self.assertIsNone(stored["messages"][1]["reasoning"])
        self.assertTrue(all(message["status"] not in {"pending", "streaming"} and message["task_id"] is None for message in stored["messages"]))
        self.assertTrue(all(message.status not in {"pending", "streaming"} and message.task_id is None for message in restored.messages))

    def test_scoped_snapshot_misses_have_one_not_found_result(self):
        session = self._live_session()
        snapshot = self.sessions.save(session.id, self.project.project_id, "owner-1", "Parser fix", "fix", [])
        other_root = self.root / "different"
        other_root.mkdir()
        other = self.registry.register(other_root)

        for project_id, owner, snapshot_id in (
            (self.project.project_id, "owner-1", "f" * 32),
            (self.project.project_id, "owner-2", snapshot.id),
            (other.project_id, "owner-1", snapshot.id),
        ):
            with self.subTest(project_id=project_id, owner=owner), self.assertRaises(KeyError):
                self.sessions.get(snapshot_id, project_id, owner)

    def test_summary_keeps_required_categories_and_exact_identifiers_after_long_objective(self):
        session = self.workspace.create_session("owner-1", self.project.project_id)
        self.workspace.append_message(session.id, ChatMessage(role="user", content="x" * 20_000))
        self.workspace.append_message(session.id, ChatMessage(role="assistant", content="done", status="completed", effective_model="model-x", task_id="task-x", references=[ObjectReference(id="r-x", kind="project_file", label="src/widget.py", target="src/widget.py")]))
        self.attachments.import_text(session.id, "note", "component:Widget")
        snapshot = self.sessions.save(session.id, self.project.project_id, "owner-1", "My Title", "feature", ["component:Widget", "User Keyword"])

        self.assertLessEqual(len(snapshot.summary), 8_000)
        for text in ("Outcome (completed): done", "Model: model-x", "Task: task-x", "Reference: src/widget.py", "Attachment: component:Widget"):
            self.assertIn(text, snapshot.summary)
        for value in (f"session:{session.id}", "change-type:feature", "title:my-title", "file:src/widget.py", "component:widget", "model:model-x", "task:task-x", "reference:r-x", "user-keyword"):
            self.assertIn(value, snapshot.keywords)

    def test_save_sweeps_abandoned_same_parent_staging(self):
        session = self._live_session()
        sessions_root = self.sessions.project_directory(self.project.project_id) / "sessions"
        sessions_root.mkdir(parents=True)
        abandoned = sessions_root / (".staging-" + "a" * 32)
        abandoned.mkdir()
        (abandoned / "partial").write_text("partial", encoding="utf-8")

        self.sessions.save(session.id, self.project.project_id, "owner-1", "Parser fix", "fix", [])

        self.assertFalse(abandoned.exists())

    def test_save_request_validates_and_serializes_session_id(self):
        request = ProjectSessionSaveRequest(session_id="a" * 32, title="Title", change_type="fix")
        self.assertEqual(request.model_dump()["session_id"], "a" * 32)
        with self.assertRaises(ValueError):
            ProjectSessionSaveRequest(session_id="bad", title="Title", change_type="fix")

    def test_rejected_over_limit_and_session_limit_attachments_save_and_restore_as_metadata(self):
        session = self.workspace.create_session("owner-1", self.project.project_id)
        limited = AttachmentService(self.workspace, max_file_bytes=2, max_session_bytes=3)
        with self.assertRaises(Exception):
            limited.import_text(session.id, "toolong", "large.txt")
        other = self.workspace.create_session("owner-1", self.project.project_id)
        session_limited = AttachmentService(self.workspace, max_file_bytes=3, max_session_bytes=3)
        session_limited.import_text(other.id, "abc", "one.txt")
        with self.assertRaises(Exception):
            session_limited.import_text(other.id, "de", "two.txt")

        for current in (session, other):
            snapshot = self.sessions.save(current.id, self.project.project_id, "owner-1", "Limits", "fix", [])
            restored = self.workspace.get_session(self.sessions.restore(snapshot.id, self.project.project_id, "owner-1").session_id)
            rejected = next(item for item in restored.attachments if item.extraction_state.value == "rejected")
            self.assertIsNone(rejected.digest)

    def test_many_long_messages_preserve_each_present_summary_category(self):
        session = self.workspace.create_session("owner-1", self.project.project_id)
        for _ in range(10):
            self.workspace.append_message(session.id, ChatMessage(role="user", content="objective " * 1_000))
            self.workspace.append_message(session.id, ChatMessage(role="assistant", content="outcome " * 1_000, effective_model="model-tail", task_id="task-tail"))
        self.workspace.append_message(session.id, ChatMessage(role="assistant", content="tail", references=[ObjectReference(id="tail-ref", kind="project_file", label="tail.py", target="tail.py")]))
        attachment = self.attachments.import_text(session.id, "note", "tail.txt")
        record = self.workspace.get_session(session.id)
        record.attachments[0].warnings = ["tail-warning"]
        self.workspace.save_manifest(record)
        snapshot = self.sessions.save(session.id, self.project.project_id, "owner-1", "Long", "fix", [])
        self.assertLessEqual(len(snapshot.summary), 8_000)
        for marker in ("Outcome (completed):", "Model: model-tail", "Task: task-tail", "Reference: tail.py", "Attachment: tail.txt", "Warning: tail-warning"):
            self.assertIn(marker, snapshot.summary)

    def test_copied_file_fsync_failure_prevents_promotion_and_cleans_same_parent_staging(self):
        session = self._live_session()
        real_fsync = os.fsync
        real_destination = self.sessions._open_copy_destination
        active_writable_descriptors = set()
        observed_writable_descriptors = set()

        @contextmanager
        def track_writable_destination(destination):
            with real_destination(destination) as writer:
                descriptor = writer.fileno()
                if destination.parent.name == "originals" and any(
                    part.startswith(".staging-") for part in destination.parts
                ):
                    active_writable_descriptors.add(descriptor)
                    observed_writable_descriptors.add(descriptor)
                try:
                    yield writer
                finally:
                    active_writable_descriptors.discard(descriptor)

        def fail_copied_file(descriptor):
            if descriptor in active_writable_descriptors:
                raise OSError(errno.EIO, "copied file durability failure")
            return real_fsync(descriptor)

        with patch.object(
            self.sessions, "_open_copy_destination", side_effect=track_writable_destination
        ), patch(
            "web_app.project_sessions.os.fsync", side_effect=fail_copied_file
        ):
            with self.assertRaises(OSError):
                self.sessions.save(session.id, self.project.project_id, "owner-1", "Fail", "fix", [])
        self.assertTrue(observed_writable_descriptors)
        self.assertEqual([], self.sessions.list(self.project.project_id, "owner-1"))
        self._assert_no_staging()

    @unittest.skipUnless(os.name == "nt", "Windows transaction-root handle semantics")
    def test_save_pins_staging_root_before_sanitized_manifest_write(self):
        session = self._live_session()
        external = self.root / "external-after-handle"
        external.mkdir()

        class SwapAtCopyEntry(ProjectSessionService):
            swapped = False

            def _copy_live_session(swap_self, record, destination):
                swap_self.swapped = True
                parked = destination.with_name(destination.name + ".parked")
                destination.replace(parked)
                os.symlink(external, destination, target_is_directory=True)
                return super()._copy_live_session(record, destination)

        service = SwapAtCopyEntry(self.workspace, self.registry)
        sessions_root = service.project_directory(self.project.project_id) / "sessions"
        try:
            with self.assertRaises(OSError):
                service.save(session.id, self.project.project_id, "owner-1", "Pinned", "fix", [])
            self.assertTrue(service.swapped)
            self.assertEqual([], list(external.iterdir()))
            self.assertFalse(sessions_root.exists() and any(sessions_root.iterdir()))
        finally:
            if sessions_root.exists():
                for entry in list(sessions_root.iterdir()):
                    self.sessions._remove_tree_no_follow(entry)

    @unittest.skipUnless(os.name == "nt", "Windows transaction-root handle semantics")
    def test_save_pins_staging_root_during_snapshot_and_history_metadata_writes(self):
        session = self._live_session()
        external = self.root / "external-metadata"
        external.mkdir()
        real_write = ProjectSessionService._write_text
        attacked = []

        def swap_during_metadata(path, text):
            if path.name == "snapshot.json" and not attacked:
                attacked.append(path.parent)
                parked = path.parent.with_name(path.parent.name + ".parked")
                path.parent.replace(parked)
                os.symlink(external, path.parent, target_is_directory=True)
            return real_write(path, text)

        sessions_root = self.sessions.project_directory(self.project.project_id) / "sessions"
        try:
            with patch.object(ProjectSessionService, "_write_text", side_effect=swap_during_metadata):
                with self.assertRaises(OSError):
                    self.sessions.save(session.id, self.project.project_id, "owner-1", "Metadata", "fix", [])
            self.assertTrue(attacked)
            self.assertEqual([], list(external.iterdir()))
            self.assertFalse(sessions_root.exists() and any(sessions_root.iterdir()))
        finally:
            if sessions_root.exists():
                for entry in list(sessions_root.iterdir()):
                    self.sessions._remove_tree_no_follow(entry)

    @unittest.skipUnless(os.name == "nt", "Windows transaction-root handle semantics")
    def test_save_keeps_pinned_staging_identity_between_validation_and_promotion(self):
        session = self._live_session()
        external = self.root / "external-before-promotion"
        external.mkdir()
        real_fsync_tree = self.sessions._fsync_tree
        attacked = []

        def swap_after_validation(staging):
            real_fsync_tree(staging)
            attacked.append(staging)
            parked = staging.with_name(staging.name + ".parked")
            staging.replace(parked)
            os.symlink(external, staging, target_is_directory=True)

        sessions_root = self.sessions.project_directory(self.project.project_id) / "sessions"
        try:
            with patch.object(self.sessions, "_fsync_tree", side_effect=swap_after_validation):
                with self.assertRaises(OSError):
                    self.sessions.save(session.id, self.project.project_id, "owner-1", "Promote", "fix", [])
            self.assertTrue(attacked)
            self.assertEqual([], list(external.iterdir()))
            self.assertFalse(sessions_root.exists() and any(sessions_root.iterdir()))
        finally:
            if sessions_root.exists():
                for entry in list(sessions_root.iterdir()):
                    self.sessions._remove_tree_no_follow(entry)

    def test_post_copy_stage_mismatch_rejects_promotion_and_cleans_staging(self):
        session = self._live_session()
        original = self.sessions._copy_live_session

        def corrupt_after_copy(record, destination):
            digests = original(record, destination)
            (destination / "artifacts" / "result.md").write_text("tampered", encoding="utf-8")
            return digests

        with patch.object(self.sessions, "_copy_live_session", side_effect=corrupt_after_copy):
            with self.assertRaisesRegex(ValueError, "digest validation"):
                self.sessions.save(session.id, self.project.project_id, "owner-1", "Mismatch", "fix", [])
        self.assertEqual([], self.sessions.list(self.project.project_id, "owner-1"))
        self._assert_no_staging()

    def test_copy_boundary_rejects_transient_source_entry_swap_for_save_and_restore(self):
        session = self._live_session()
        live = self.workspace.get_session(session.id)
        live_source = self.workspace.sessions_root / session.id / "originals" / live.attachments[0].storage_name
        external = self.root / "external-source.txt"
        external.write_bytes(live_source.read_bytes())

        class SourceSwappingService(ProjectSessionService):
            def __init__(swap_self, *args, swap_target, **kwargs):
                super().__init__(*args, **kwargs)
                swap_self.swap_target = swap_target
                swap_self.swapped = False

            @contextmanager
            def _open_copy_source(swap_self, source):
                if source == swap_self.swap_target and not swap_self.swapped:
                    swap_self.swapped = True
                    parked = source.with_name(source.name + ".parked")
                    source.replace(parked)
                    os.symlink(external, source)
                    try:
                        with super()._open_copy_source(source) as reader:
                            yield reader
                    finally:
                        if source.is_symlink():
                            source.unlink()
                        if parked.exists():
                            parked.replace(source)
                    return
                with super()._open_copy_source(source) as reader:
                    yield reader

        swapping_save = SourceSwappingService(
            self.workspace, self.registry, swap_target=live_source
        )
        with self.assertRaises(ValueError):
            swapping_save.save(session.id, self.project.project_id, "owner-1", "Swap", "fix", [])
        self.assertTrue(swapping_save.swapped)
        self.assertEqual(b"attachment text", external.read_bytes())
        self.assertEqual([], self.sessions.list(self.project.project_id, "owner-1"))
        self._assert_no_staging()

        snapshot = self.sessions.save(
            session.id, self.project.project_id, "owner-1", "Restore source", "fix", []
        )
        stored = json.loads(
            (self.sessions.snapshot_directory(snapshot.id, self.project.project_id) / "manifest.json").read_text(
                encoding="utf-8"
            )
        )
        snapshot_source = (
            self.sessions.snapshot_directory(snapshot.id, self.project.project_id)
            / "originals"
            / stored["attachments"][0]["storage_name"]
        )
        before_sessions = {path.name for path in self.workspace.sessions_root.iterdir()}
        swapping_restore = SourceSwappingService(
            self.workspace, self.registry, swap_target=snapshot_source
        )
        with self.assertRaises(ValueError):
            swapping_restore.restore(snapshot.id, self.project.project_id, "owner-1")
        self.assertTrue(swapping_restore.swapped)
        self.assertEqual(before_sessions, {path.name for path in self.workspace.sessions_root.iterdir()})

    def test_copy_boundary_rejects_transient_destination_root_swap_without_external_write(self):
        session = self._live_session()
        external = self.root / "external-destination"
        external.mkdir()

        class DestinationSwappingService(ProjectSessionService):
            def __init__(swap_self, *args, restore_mode=False, **kwargs):
                super().__init__(*args, **kwargs)
                swap_self.restore_mode = restore_mode
                swap_self.swapped = False

            @contextmanager
            def _create_copy_directory(swap_self, destination):
                is_restore = self.workspace.sessions_root in destination.parents
                if is_restore == swap_self.restore_mode and not swap_self.swapped:
                    swap_self.swapped = True
                    if is_restore:
                        root = next(
                            parent for parent in destination.parents
                            if parent.parent == self.workspace.sessions_root
                        )
                    else:
                        root = next(
                            parent for parent in destination.parents
                            if parent.name.startswith(".staging-")
                        )
                    parked = root.with_name(root.name + ".parked")
                    root.replace(parked)
                    os.symlink(external, root, target_is_directory=True)
                    try:
                        with super()._create_copy_directory(destination):
                            yield
                    finally:
                        if root.is_symlink():
                            root.unlink()
                        if parked.exists():
                            parked.replace(root)
                    return
                with super()._create_copy_directory(destination):
                    yield

        swapping_save = DestinationSwappingService(self.workspace, self.registry)
        with self.assertRaises((OSError, ValueError)):
            swapping_save.save(session.id, self.project.project_id, "owner-1", "Swap", "fix", [])
        self.assertTrue(swapping_save.swapped)
        self.assertEqual([], list(external.iterdir()))
        self.assertEqual([], self.sessions.list(self.project.project_id, "owner-1"))
        self._assert_no_staging()

        snapshot = self.sessions.save(
            session.id, self.project.project_id, "owner-1", "Restore destination", "fix", []
        )
        before_sessions = {path.name for path in self.workspace.sessions_root.iterdir()}
        swapping_restore = DestinationSwappingService(
            self.workspace, self.registry, restore_mode=True
        )
        with self.assertRaises((OSError, ValueError)):
            swapping_restore.restore(snapshot.id, self.project.project_id, "owner-1")
        self.assertTrue(swapping_restore.swapped)
        self.assertEqual([], list(external.iterdir()))
        self.assertEqual(before_sessions, {path.name for path in self.workspace.sessions_root.iterdir()})

    @unittest.skipUnless(os.name == "nt", "Windows transaction-root handle semantics")
    def test_restore_pins_target_root_through_validation_and_final_manifest_commit(self):
        session = self._live_session()
        snapshot = self.sessions.save(
            session.id, self.project.project_id, "owner-1", "Restore pin", "fix", []
        )
        external = self.root / "external-restore-target"
        external.mkdir()
        sentinel = external / "sentinel.txt"
        sentinel.write_text("untouched", encoding="utf-8")

        for phase in ("validation", "manifest"):
            with self.subTest(phase=phase):
                before = {path.name for path in self.workspace.sessions_root.iterdir()}
                attacked = []
                real_validate = self.sessions._validate_restored_trees
                real_save_manifest = self.workspace.save_manifest

                def swap_target(target):
                    attacked.append(target)
                    parked = target.with_name(target.name + ".parked")
                    target.replace(parked)
                    os.symlink(external, target, target_is_directory=True)

                def attack_after_validation(directory, expected):
                    real_validate(directory, expected)
                    swap_target(directory)

                def attack_at_manifest(record):
                    if record.restored_from_snapshot_id:
                        swap_target(self.workspace.sessions_root / record.id)
                    return real_save_manifest(record)

                validate_patch = (
                    patch.object(self.sessions, "_validate_restored_trees", side_effect=attack_after_validation)
                    if phase == "validation"
                    else patch.object(self.sessions, "_validate_restored_trees", wraps=real_validate)
                )
                manifest_patch = (
                    patch.object(self.workspace, "save_manifest", side_effect=attack_at_manifest)
                    if phase == "manifest"
                    else patch.object(self.workspace, "save_manifest", wraps=real_save_manifest)
                )
                try:
                    with validate_patch, manifest_patch:
                        with self.assertRaises(OSError):
                            self.sessions.restore(snapshot.id, self.project.project_id, "owner-1")
                    self.assertTrue(attacked)
                    self.assertEqual("untouched", sentinel.read_text(encoding="utf-8"))
                    self.assertEqual(before, {path.name for path in self.workspace.sessions_root.iterdir()})
                finally:
                    for entry in list(self.workspace.sessions_root.iterdir()):
                        if entry.name not in before:
                            self.sessions._remove_tree_no_follow(entry)

    def test_restore_rollback_removes_persistently_swapped_allocated_root_without_following_it(self):
        session = self._live_session()
        snapshot = self.sessions.save(
            session.id, self.project.project_id, "owner-1", "Rollback", "fix", []
        )
        external = self.root / "external-persistent-restore"
        external.mkdir()
        sentinel = external / "sentinel.txt"
        sentinel.write_text("external data", encoding="utf-8")
        before = {path.name for path in self.workspace.sessions_root.iterdir()}
        real_save_manifest = self.workspace.save_manifest
        real_delete_session = self.workspace.delete_session
        swapped = []

        def fail_final_manifest(record):
            if record.restored_from_snapshot_id:
                raise OSError("final restored manifest commit failed")
            return real_save_manifest(record)

        def leave_swapped_root_for_rollback(session_id):
            target = self.workspace.sessions_root / session_id
            parked = target.with_name(target.name + ".parked")
            target.replace(parked)
            os.symlink(external, target, target_is_directory=True)
            swapped.append((target, parked))
            return real_delete_session(session_id)

        try:
            with patch.object(self.workspace, "save_manifest", side_effect=fail_final_manifest), patch.object(
                self.workspace, "delete_session", side_effect=leave_swapped_root_for_rollback
            ):
                with self.assertRaisesRegex(OSError, "final restored manifest commit failed"):
                    self.sessions.restore(snapshot.id, self.project.project_id, "owner-1")
            self.assertTrue(swapped)
            self.assertEqual("external data", sentinel.read_text(encoding="utf-8"))
            self.assertEqual(before, {path.name for path in self.workspace.sessions_root.iterdir()})
        finally:
            for entry in list(self.workspace.sessions_root.iterdir()):
                if entry.name not in before:
                    self.sessions._remove_tree_no_follow(entry)

    def test_save_barrier_with_message_append_has_complete_before_or_after_snapshot(self):
        session = self._live_session()
        entered, release = threading.Event(), threading.Event()
        original = self.sessions._copy_live_session
        def pause(record, destination):
            entered.set()
            self.assertTrue(release.wait(3))
            return original(record, destination)
        save_result, append_result = {}, {}
        with patch.object(self.sessions, "_copy_live_session", side_effect=pause):
            worker = threading.Thread(target=self._run_worker, args=(save_result, lambda: self.sessions.save(session.id, self.project.project_id, "owner-1", "Race", "fix", [])))
            worker.start()
            self.assertTrue(entered.wait(1))
            append = threading.Thread(target=self._run_worker, args=(append_result, lambda: self.workspace.append_message(session.id, ChatMessage(role="user", content="after"))))
            append.start()
            self.assertTrue(append.is_alive())
            release.set()
            worker.join(3)
            append.join(3)
        self.assertFalse(worker.is_alive())
        self.assertFalse(append.is_alive())
        self.assertNotIn("error", save_result)
        self.assertNotIn("error", append_result)
        saved = json.loads((self.sessions.snapshot_directory(save_result["result"].id, self.project.project_id) / "manifest.json").read_text())
        self.assertEqual(2, len(saved["messages"]))
        self.assertEqual(3, len(self.workspace.get_session(session.id).messages))

    def test_attachment_mutations_race_save_as_complete_before_or_after(self):
        for operation in ("import", "update", "retry", "remove"):
            with self.subTest(operation=operation):
                session = self._live_session()
                attachment = self.workspace.get_session(session.id).attachments[0]
                session_directory = self.workspace.sessions_root / session.id
                if operation == "retry":
                    record = self.workspace.get_session(session.id)
                    retry_attachment = record.attachments[0]
                    (session_directory / "extracted" / retry_attachment.extracted_name).unlink()
                    retry_attachment.extracted_name = None
                    retry_attachment.extraction_state = ExtractionState.rejected
                    retry_attachment.included = False
                    retry_attachment.warnings = ["retry required"]
                    self.workspace.save_manifest(record)
                before = self._attachment_state(session_directory)
                entered, release = threading.Event(), threading.Event()
                original = self.sessions._copy_live_session
                def pause(record, destination):
                    entered.set()
                    self.assertTrue(release.wait(3))
                    return original(record, destination)
                save_result, mutation_result = {}, {}
                with patch.object(self.sessions, "_copy_live_session", side_effect=pause):
                    save_thread = threading.Thread(target=self._run_worker, args=(save_result, lambda: self.sessions.save(session.id, self.project.project_id, "owner-1", "Race", "fix", [])))
                    save_thread.start()
                    self.assertTrue(entered.wait(1))
                    if operation == "import": action = lambda: self.attachments.import_text(session.id, "new", "new.txt")
                    elif operation == "update": action = lambda: self.attachments.set_included(session.id, attachment.id, False)
                    elif operation == "retry": action = lambda: self.attachments.retry(session.id, attachment.id)
                    else: action = lambda: self.attachments.remove(session.id, attachment.id)
                    mutate = threading.Thread(target=self._run_worker, args=(mutation_result, action))
                    mutate.start()
                    self.assertTrue(mutate.is_alive())
                    release.set()
                    save_thread.join(3)
                    mutate.join(3)
                self.assertFalse(save_thread.is_alive())
                self.assertFalse(mutate.is_alive())
                self.assertNotIn("error", save_result)
                self.assertNotIn("error", mutation_result)
                after = self._attachment_state(session_directory)
                if operation == "retry":
                    self.assertNotEqual(before, after)
                    self.assertEqual("ready", after["attachments"][0]["extraction_state"])
                    self.assertTrue(after["files"]["extracted"])
                snapshot_directory = self.sessions.snapshot_directory(save_result["result"].id, self.project.project_id)
                self.assertIn(self._attachment_state(snapshot_directory), (before, after))

    def test_failure_after_staging_and_after_restore_allocation_cleans_everything(self):
        session = self._live_session()
        with patch.object(self.sessions, "_write_text", side_effect=OSError("after staging")):
            with self.assertRaises(OSError): self.sessions.save(session.id, self.project.project_id, "owner-1", "Fail", "fix", [])
        root = self.sessions.project_directory(self.project.project_id) / "sessions"
        self.assertFalse(root.exists() and any(path.name.startswith(".staging-") for path in root.iterdir()))
        snapshot = self.sessions.save(session.id, self.project.project_id, "owner-1", "OK", "fix", [])
        before = {path.name for path in self.workspace.sessions_root.iterdir()}
        with patch.object(self.sessions, "_copy_snapshot_trees", side_effect=OSError("after allocation")):
            with self.assertRaises(OSError): self.sessions.restore(snapshot.id, self.project.project_id, "owner-1")
        self.assertEqual(before, {path.name for path in self.workspace.sessions_root.iterdir()})

    def test_forced_overlapping_project_saves_block_and_preserve_each_complete_source(self):
        first = self._live_session()
        second = self.workspace.create_session("owner-1", self.project.project_id)
        self.workspace.append_message(second.id, ChatMessage(role="user", content="second"))
        self.attachments.import_text(second.id, "second attachment", "second.txt")
        second_artifacts = self.workspace.sessions_root / second.id / "artifacts"
        second_artifacts.mkdir()
        (second_artifacts / "second.md").write_text("second artifact", encoding="utf-8")
        expected_attachments = {
            first.id: self._attachment_state(self.workspace.sessions_root / first.id),
            second.id: self._attachment_state(self.workspace.sessions_root / second.id),
        }
        first_entered, release_first, second_entered = threading.Event(), threading.Event(), threading.Event()
        original = self.sessions._copy_live_session

        def pause_first(record, destination):
            if record.id == first.id:
                first_entered.set()
                self.assertTrue(release_first.wait(3))
            else:
                second_entered.set()
            return original(record, destination)

        results = {first.id: {}, second.id: {}}
        workers = {
            current.id: threading.Thread(
                target=self._run_worker,
                args=(results[current.id], lambda current=current: self.sessions.save(current.id, self.project.project_id, "owner-1", current.id, "fix", [])),
            )
            for current in (first, second)
        }
        with patch.object(self.sessions, "_copy_live_session", side_effect=pause_first):
            workers[first.id].start()
            self.assertTrue(first_entered.wait(1))
            workers[second.id].start()
            self.assertFalse(second_entered.wait(0.25))
            self.assertTrue(workers[second.id].is_alive())
            release_first.set()
            for worker in workers.values():
                worker.join(3)
        for worker in workers.values():
            self.assertFalse(worker.is_alive())
        for output in results.values():
            self.assertNotIn("error", output)
        self.assertTrue(second_entered.is_set())
        snapshots = {session_id: output["result"] for session_id, output in results.items()}
        self.assertNotEqual(snapshots[first.id].id, snapshots[second.id].id)
        first_manifest = json.loads((self.sessions.snapshot_directory(snapshots[first.id].id, self.project.project_id) / "manifest.json").read_text(encoding="utf-8"))
        second_directory = self.sessions.snapshot_directory(snapshots[second.id].id, self.project.project_id)
        second_manifest = json.loads((second_directory / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(["Implement parser.py and verify the model output.", "Parser implementation completed."], [message["content"] for message in first_manifest["messages"]])
        self.assertEqual(["notes.txt"], [item["display_name"] for item in first_manifest["attachments"]])
        self.assertEqual(["second"], [message["content"] for message in second_manifest["messages"]])
        self.assertEqual(["second.txt"], [item["display_name"] for item in second_manifest["attachments"]])
        self.assertEqual(expected_attachments[first.id], self._attachment_state(self.sessions.snapshot_directory(snapshots[first.id].id, self.project.project_id)))
        self.assertEqual(expected_attachments[second.id], self._attachment_state(second_directory))
        self.assertEqual("artifact", (self.sessions.snapshot_directory(snapshots[first.id].id, self.project.project_id) / "artifacts" / "result.md").read_text(encoding="utf-8"))
        self.assertEqual("second artifact", (second_directory / "artifacts" / "second.md").read_text(encoding="utf-8"))
        root = self.sessions.project_directory(self.project.project_id) / "sessions"
        self.assertFalse(any(path.name.startswith(".staging-") for path in root.iterdir()))


if __name__ == "__main__":
    unittest.main()
