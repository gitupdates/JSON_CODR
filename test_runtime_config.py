import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from web_app.core.cli import _parser
from web_app.runtime_config import RuntimeConfig


ROOT = Path(__file__).resolve().parent


class RuntimeConfigTests(unittest.TestCase):
    def test_repository_config_is_the_canonical_runtime_contract(self):
        """Changing the repository contract must change every configured value together."""
        raw = json.loads((ROOT / "config" / "runtime.json").read_text(encoding="utf-8"))
        config = RuntimeConfig.load()

        self.assertEqual(config.schema_version, raw["schema_version"])
        self.assertEqual(config.version, raw["version"])
        self.assertEqual(config.host, raw["host"])
        self.assertEqual(config.port, raw["port"])
        self.assertEqual(config.url, "http://127.0.0.1:8765")
        self.assertEqual(config.health_path, "/api/health")
        self.assertEqual(config.runtime_status_path, "/api/runtime/status")
        self.assertEqual(config.tasks_path, "/api/tasks")
        self.assertEqual(config.host_python_versions, ("3.14", "3.15"))
        self.assertEqual(config.compatible_python_versions, ("3.11", "3.12"))
        self.assertTrue(
            {
                "JSON_CODR_DATA_ROOT",
                "JSON_CODR_LAUNCHER_ROOT",
                "JSON_CODR_PYTHON",
                "JSON_CODR_COMPATIBLE_PYTHON",
                "JSON_CODR_MODELS",
            }.issubset(config.allowed_environment_overrides)
        )
        self.assertEqual(len(config.receipt_digest()), 64)

    def test_cli_defaults_use_the_canonical_server_url(self):
        """A changed endpoint must reach every CLI entry point, rather than leaving a stale port."""
        parser = _parser()
        config = RuntimeConfig.load()

        self.assertEqual(parser.parse_args(["status"]).url, config.url)
        self.assertEqual(
            parser.parse_args(["run", "prompt", "--project", "."]).url,
            config.url,
        )
        self.assertEqual(parser.parse_args(["auth", "login"]).url, config.url)

    def test_unknown_json_codr_environment_override_is_rejected(self):
        """An undeclared JSON_CODR input must not create a hidden runtime default."""
        with patch.dict(os.environ, {"JSON_CODR_UNDECLARED_OVERRIDE": "surprise"}, clear=False):
            with self.assertRaisesRegex(ValueError, "undeclared environment override"):
                RuntimeConfig.load()

    def test_config_rejects_unknown_schema_keys(self):
        """Typos in the machine-readable contract must fail instead of being ignored."""
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "runtime.json"
            raw = json.loads((ROOT / "config" / "runtime.json").read_text(encoding="utf-8"))
            raw["surprise"] = True
            path.write_text(json.dumps(raw), encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "unknown runtime configuration keys"):
                RuntimeConfig.load(path)


if __name__ == "__main__":
    unittest.main()
