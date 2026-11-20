import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from web_app.localperf.aggregate import aggregate_run
from web_app.localperf.models import SampleRecord
from web_app.localperf.storage import LocalPerfStorage


class LocalPerfPackageTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.storage = LocalPerfStorage(self.root)
        samples = [SampleRecord(
            prompt_id="lp-01", repetition=1, success=True, generation_tokens_per_second=20,
            ttft_ms=10, peak_vram_mb=100, total_duration_ms=100, prompt_tokens=2,
            generated_tokens=2, output="ok",
        )]
        metadata = {
            "model": "qwen", "backend": "cpu", "profile": "automatic",
            "hardware": {"cpu": "Secret Workstation", "serial": "ABC123"},
            "software": {"application": "JSON_CODR", "version": "V1.0.11", "python_path": "C:/Users/Test/python.exe"},
        }
        self.run = aggregate_run(samples, metadata, "quick", 1)
        self.storage.save_run(self.run)

    def tearDown(self):
        self.temporary.cleanup()

    def test_default_export_is_sanitized_and_has_required_checked_members(self):
        from web_app.localperf.package import LocalPerfPackageService

        artifact = LocalPerfPackageService(self.storage).export(self.run.evaluation_id)
        self.assertRegex(artifact.filename, r"^json-codr-localperf-core-v1-1\.0-\d{8}T\d{6}Z\.localperf\.zip$")
        with zipfile.ZipFile(io.BytesIO(artifact.content)) as archive:
            names = set(archive.namelist())
            required = {"manifest.json", "standard/workload.json", "standard/localperf_run.schema.json",
                        "standard/METHOD.md", "standard/REPORT-TEMPLATE.md",
                        "reference/aggregate.json", "reference/samples.jsonl"}
            self.assertEqual(names, required)
            manifest = json.loads(archive.read("manifest.json"))
            aggregate = json.loads(archive.read("reference/aggregate.json"))
        self.assertFalse(manifest["include_system_details"])
        self.assertEqual(set(manifest["checksums"]), required - {"manifest.json"})
        self.assertEqual(aggregate["configuration"]["hardware"], {"sanitized": True, "kind": "cpu"})
        self.assertEqual(aggregate["configuration"]["software"], {"sanitized": True, "application": "JSON_CODR", "version": "V1.0.11"})
        self.assertNotIn("Secret Workstation", artifact.content.decode("latin1"))

    def test_details_require_explicit_export_opt_in(self):
        from web_app.localperf.package import LocalPerfPackageService

        artifact = LocalPerfPackageService(self.storage).export(self.run.evaluation_id, include_system_details=True)
        with zipfile.ZipFile(io.BytesIO(artifact.content)) as archive:
            manifest = json.loads(archive.read("manifest.json"))
            aggregate = json.loads(archive.read("reference/aggregate.json"))
        self.assertTrue(manifest["include_system_details"])
        self.assertEqual(aggregate["configuration"]["hardware"]["serial"], "ABC123")

    def test_preview_validates_checksums_without_persisting(self):
        from web_app.localperf.package import LocalPerfPackageService

        service = LocalPerfPackageService(self.storage)
        artifact = service.export(self.run.evaluation_id)
        preview = service.preview(artifact.content)
        self.assertTrue(preview.valid)
        self.assertFalse(preview.contains_system_details)
        self.assertFalse((self.root / "localperf" / "imports").exists())

    def test_import_requires_consent_for_details_and_labels_source(self):
        from web_app.localperf.package import LocalPerfPackageError, LocalPerfPackageService

        service = LocalPerfPackageService(self.storage)
        detailed = service.export(self.run.evaluation_id, include_system_details=True)
        with self.assertRaisesRegex(LocalPerfPackageError, "consent"):
            service.import_package(detailed.content)
        record = service.import_package(detailed.content, retain_system_details=True)
        aggregate = json.loads((record.path / "reference" / "aggregate.json").read_text())
        self.assertEqual(aggregate["source"], "imported")
        self.assertFalse(aggregate["eligible_as_local_baseline"])

    def test_preview_rejects_traversal_and_checksum_tampering(self):
        from web_app.localperf.package import LocalPerfPackageError, LocalPerfPackageService

        service = LocalPerfPackageService(self.storage)
        payload = io.BytesIO()
        with zipfile.ZipFile(payload, "w") as archive:
            archive.writestr("../escape.json", "{}")
        with self.assertRaises(LocalPerfPackageError):
            service.preview(payload.getvalue())

        artifact = service.export(self.run.evaluation_id)
        source = zipfile.ZipFile(io.BytesIO(artifact.content))
        changed = io.BytesIO()
        with zipfile.ZipFile(changed, "w") as archive:
            for name in source.namelist():
                content = source.read(name)
                archive.writestr(name, b"changed" if name == "reference/samples.jsonl" else content)
        with self.assertRaisesRegex(LocalPerfPackageError, "checksum"):
            service.preview(changed.getvalue())


if __name__ == "__main__":
    unittest.main()
