import os
import tempfile
import unittest
from pathlib import Path

from web_app.designer.contracts import DesignDocument, DesignNode, DesignPage
from web_app.designer.store import DesignerStore, ProjectConflict


def changed(document: DesignDocument, name: str) -> DesignDocument:
    payload = document.model_dump(mode="json", exclude={"canonical_digest"})
    payload["name"] = name
    return DesignDocument.model_validate(payload)


class DesignerStoreTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)
        self.store = DesignerStore(self.root)

    def tearDown(self):
        self.temporary_directory.cleanup()

    def test_create_generates_confined_identity_and_reopens(self):
        created = self.store.create_project("blank", "Status board")

        self.assertRegex(created.project_id, r"^design-[0-9a-f]{32}$")
        self.assertEqual(created.name, "Status board")
        self.assertEqual(self.store.get_project(created.project_id), created)
        reopened = DesignerStore(self.root)
        self.assertEqual(reopened.get_project(created.project_id), created)
        self.assertEqual(
            (self.root / "designer" / "projects" / created.project_id).resolve().parent,
            (self.root / "designer" / "projects").resolve(),
        )

    def test_revision_is_parent_linked_immutable_and_requires_current_digest(self):
        created = self.store.create_project("blank", "First")
        first_revision = self.store.list_revisions(created.project_id)[0]
        updated = changed(created, "Second")

        saved = self.store.save_revision(created.project_id, updated, created.canonical_digest)

        self.assertEqual(saved.parent_revision_id, first_revision.revision_id)
        self.assertEqual(saved.document.name, "Second")
        self.assertEqual(self.store.list_revisions(created.project_id), (first_revision, saved))
        with self.assertRaisesRegex(ProjectConflict, "current digest"):
            self.store.save_revision(created.project_id, changed(updated, "Stale"), created.canonical_digest)
        self.assertEqual(self.store.list_revisions(created.project_id)[0], first_revision)

    def test_draft_recovers_after_reopen_without_replacing_explicit_revision(self):
        created = self.store.create_project("blank", "Saved")
        draft = changed(created, "Unsaved draft")

        self.store.save_draft(created.project_id, draft, created.canonical_digest)

        reopened = DesignerStore(self.root)
        self.assertEqual(reopened.get_project(created.project_id).name, "Saved")
        self.assertEqual(reopened.get_draft(created.project_id), draft)
        self.assertEqual(len(reopened.list_revisions(created.project_id)), 1)

    def test_restore_appends_revision_and_preserves_historical_file(self):
        created = self.store.create_project("blank", "One")
        first = self.store.list_revisions(created.project_id)[0]
        second_document = changed(created, "Two")
        second = self.store.save_revision(created.project_id, second_document, created.canonical_digest)
        first_path = self.root / "designer" / "projects" / created.project_id / "revisions" / f"{first.revision_id}.json"
        before = first_path.read_bytes()

        restored = self.store.restore_revision(created.project_id, first.revision_id, second.document.canonical_digest)

        self.assertEqual(restored.document.name, "One")
        self.assertEqual(restored.parent_revision_id, second.revision_id)
        self.assertEqual(first_path.read_bytes(), before)
        self.assertEqual(len(self.store.list_revisions(created.project_id)), 3)

    def test_duplicate_gets_new_identity_and_independent_history(self):
        original = self.store.create_project("blank", "Original")

        duplicate = self.store.duplicate_project(original.project_id, "Copy")

        self.assertNotEqual(duplicate.project_id, original.project_id)
        self.assertEqual(duplicate.name, "Copy")
        self.assertEqual(duplicate.metadata["duplicated_from"], original.project_id)
        self.assertEqual(len(self.store.list_revisions(original.project_id)), 1)
        self.assertEqual(len(self.store.list_revisions(duplicate.project_id)), 1)

    def test_invalid_or_wrong_project_identifiers_never_escape_root(self):
        created = self.store.create_project("blank", "Confined")
        wrong = DesignDocument(
            project_id="another-project",
            name="Wrong",
            pages=(DesignPage(page_id="home", slug="home", root_node_id="root"),),
            nodes=(DesignNode(node_id="root", component_type="container"),),
        )

        for value in ("../escape", "C:\\escape", "", "."):
            with self.subTest(value=value):
                with self.assertRaises((ValueError, KeyError)):
                    self.store.get_project(value)
        with self.assertRaisesRegex(ValueError, "belongs to another project"):
            self.store.save_revision(created.project_id, wrong, created.canonical_digest)

    def test_delete_requires_token_bound_to_current_state(self):
        created = self.store.create_project("blank", "Disposable")
        stale_token = self.store.deletion_token(created.project_id)
        saved = self.store.save_revision(created.project_id, changed(created, "Changed"), created.canonical_digest)

        with self.assertRaisesRegex(ProjectConflict, "confirmation token"):
            self.store.delete_project(created.project_id, stale_token)
        current_token = self.store.deletion_token(created.project_id)
        self.store.delete_project(created.project_id, current_token)
        with self.assertRaises(KeyError):
            self.store.get_project(created.project_id)
        self.assertEqual(saved.document.name, "Changed")

    def test_failed_manifest_replace_leaves_previous_revision_current(self):
        created = self.store.create_project("blank", "Stable")

        def fail_manifest(source, target):
            if Path(target).name == "manifest.json":
                raise OSError("injected replace failure")
            os.replace(source, target)

        failing = DesignerStore(self.root, replace_file=fail_manifest)
        with self.assertRaisesRegex(OSError, "injected"):
            failing.save_revision(created.project_id, changed(created, "Should not win"), created.canonical_digest)

        reopened = DesignerStore(self.root)
        self.assertEqual(reopened.get_project(created.project_id), created)
        self.assertEqual(len(reopened.list_revisions(created.project_id)), 1)


if __name__ == "__main__":
    unittest.main()
