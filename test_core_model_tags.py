import json
import tempfile
import unittest
from pathlib import Path


class ModelTagRegistryTests(unittest.TestCase):
    def _registry(self, root: Path, payload: dict):
        from web_app.core.model_tags import ModelTagRegistry

        path = root / "models.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        return ModelTagRegistry.load(path)

    def test_corrupt_registry_is_rejected(self):
        from web_app.core.model_tags import ModelTagRegistry

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "models.json"
            path.write_text("{not json", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "model registry"):
                ModelTagRegistry.load(path)

    def test_missing_preferred_model_falls_back_truthfully(self):
        with tempfile.TemporaryDirectory() as directory:
            registry = self._registry(Path(directory), {
                "schema_version": 1,
                "fallback_order": ["qwen3:4b", "qwen2.5-coder:0.5b"],
                "tags": {"coding": {
                    "models": ["missing:70b", "qwen3:4b"],
                    "skills": [],
                    "endpoint": "http://127.0.0.1:11434",
                    "num_ctx": 16384,
                    "temperature": 0.1,
                }},
            })

            route = registry.resolve("coding", {"qwen3:4b", "qwen2.5-coder:0.5b"})

            self.assertEqual(route.requested, "coding")
            self.assertEqual(route.effective_model, "qwen3:4b")
            self.assertTrue(route.fallback_used)
            self.assertIn("missing:70b", route.unavailable_models)
            self.assertEqual(route.options, {"num_ctx": 16384, "temperature": 0.1})

    def test_unknown_tag_can_resolve_an_exact_installed_model(self):
        with tempfile.TemporaryDirectory() as directory:
            registry = self._registry(Path(directory), {
                "schema_version": 1,
                "fallback_order": ["qwen3:4b"],
                "tags": {},
            })
            route = registry.resolve("granite-code:8b-instruct", {"granite-code:8b-instruct"})
            self.assertEqual(route.effective_model, "granite-code:8b-instruct")
            self.assertFalse(route.fallback_used)

    def test_missing_explicit_model_is_left_for_compatibility_policy(self):
        with tempfile.TemporaryDirectory() as directory:
            registry = self._registry(Path(directory), {
                "schema_version": 1,
                "fallback_order": ["qwen3:4b"],
                "tags": {},
            })

            route = registry.resolve("missing:8b", {"qwen3:4b"})

            self.assertEqual(route.effective_model, "missing:8b")
            self.assertFalse(route.fallback_used)

    def test_malformed_colon_model_is_not_treated_as_an_exact_reference(self):
        with tempfile.TemporaryDirectory() as directory:
            registry = self._registry(Path(directory), {
                "schema_version": 1,
                "fallback_order": ["qwen3:4b"],
                "tags": {},
            })

            with self.assertRaisesRegex(ValueError, "no installed model"):
                registry.resolve("missing: 8b", {"qwen3:4b"})

    def test_prompt_compilation_orders_project_instructions_then_skills_then_task(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "src").mkdir()
            (root / "AGENTS.md").write_text("ROOT RULE", encoding="utf-8")
            (root / "src" / "AGENTS.md").write_text("SCOPED RULE", encoding="utf-8")
            (root / "skills").mkdir()
            (root / "skills" / "review.md").write_text("REVIEW SKILL", encoding="utf-8")
            registry = self._registry(root, {
                "schema_version": 1,
                "fallback_order": ["qwen3:4b"],
                "tags": {"coding": {"models": ["qwen3:4b"], "skills": ["skills/review.md"]}},
            })

            compiled = registry.compile_prompt("coding", root, "Fix the bug", target="src/main.py")

            self.assertLess(compiled.text.index("ROOT RULE"), compiled.text.index("SCOPED RULE"))
            self.assertLess(compiled.text.index("SCOPED RULE"), compiled.text.index("REVIEW SKILL"))
            self.assertLess(compiled.text.index("REVIEW SKILL"), compiled.text.index("Fix the bug"))
            self.assertEqual(compiled.instruction_paths, ("AGENTS.md", "src/AGENTS.md"))
            self.assertEqual(compiled.skill_paths, ("skills/review.md",))


if __name__ == "__main__":
    unittest.main()
