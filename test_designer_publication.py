import tempfile
import unittest
from pathlib import Path

from web_app.designer.access import DesignPolicyContext
from web_app.designer.contracts import DesignDocument
from web_app.designer.publication import PublicationRejected, PublicationService
from web_app.designer.store import DesignerStore, ProjectConflict
from web_app.designer.json_codr_manifest import create_json_codr_overlay


class DesignerPublicationTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.store = DesignerStore(Path(self.temporary_directory.name))
        self.document = self.store.create_project("blank", "Continuity test")
        self.context = DesignPolicyContext(subject_id="account-admin", role="administrator")

    def tearDown(self):
        self.temporary_directory.cleanup()

    @staticmethod
    def renamed(document: DesignDocument, name: str) -> DesignDocument:
        payload = document.model_dump(mode="json", exclude={"canonical_digest"})
        payload["name"] = name
        return DesignDocument.model_validate(payload)

    def service(self, **options) -> PublicationService:
        return PublicationService(self.store, **options)

    def test_invalid_draft_cannot_change_current_snapshot(self):
        service = self.service()
        first = service.publish(self.document.project_id, self.document, None, self.context)
        invalid = self.renamed(self.document, "Rejected")
        rejecting = self.service(validator=lambda _document: ("core navigation is unreachable",))

        with self.assertRaises(PublicationRejected):
            rejecting.publish(self.document.project_id, invalid, first.revision_id, self.context)

        self.assertEqual(service.current(self.document.project_id), first)

    def test_stale_expected_revision_returns_conflict(self):
        service = self.service()
        first = service.publish(self.document.project_id, self.document, None, self.context)

        with self.assertRaises(ProjectConflict):
            service.publish(
                self.document.project_id,
                self.renamed(self.document, "Stale update"),
                "revision-not-current",
                self.context,
            )

        self.assertEqual(service.current(self.document.project_id), first)

    def test_materialization_failure_retains_last_known_good_snapshot(self):
        service = self.service()
        first = service.publish(self.document.project_id, self.document, None, self.context)

        def fail_materialization(_snapshot):
            raise OSError("simulated materialization failure")

        failing = self.service(materializer=fail_materialization)
        with self.assertRaises(OSError):
            failing.publish(
                self.document.project_id,
                self.renamed(self.document, "Never active"),
                first.revision_id,
                self.context,
            )

        self.assertEqual(service.current(self.document.project_id), first)

    def test_reader_observes_whole_old_or_whole_new_snapshot(self):
        service = self.service()
        first = service.publish(self.document.project_id, self.document, None, self.context)
        observed = []
        publishing = self.service(before_swap=lambda project_id: observed.append(service.current(project_id)))

        second = publishing.publish(
            self.document.project_id,
            self.renamed(self.document, "Atomic replacement"),
            first.revision_id,
            self.context,
        )

        self.assertEqual(observed, [first])
        self.assertEqual(service.current(self.document.project_id), second)
        self.assertNotEqual(first.revision_id, second.revision_id)

    def test_default_publication_rejects_a_design_without_core_routes(self):
        overlay = create_json_codr_overlay()
        overlay_store = DesignerStore(Path(self.temporary_directory.name) / "overlay")
        overlay_store._initialize_project(overlay)
        payload = overlay.model_dump(mode="json", exclude={"canonical_digest"})
        payload["nodes"] = [node for node in payload["nodes"] if node["node_id"] != "primary-navigation"]
        shell = next(node for node in payload["nodes"] if node["node_id"] == "application-shell")
        shell["children"] = [node_id for node_id in shell["children"] if node_id != "primary-navigation"]
        invalid = DesignDocument.model_validate(payload)

        with self.assertRaises(PublicationRejected):
            PublicationService(overlay_store).publish(overlay.project_id, invalid, None, self.context)


if __name__ == "__main__":
    unittest.main()
