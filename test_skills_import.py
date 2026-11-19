import subprocess
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent


class SkillModuleImportTests(unittest.TestCase):
    def test_skill_module_imports_in_fresh_interpreter(self) -> None:
        result = subprocess.run(
            [sys.executable, "-c", "import web_app.skills"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
