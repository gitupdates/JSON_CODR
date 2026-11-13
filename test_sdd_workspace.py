import subprocess
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).parent / "scripts" / "sdd-workspace.ps1"


class SddWorkspacePowerShellTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.repo = Path(self.temporary_directory.name)
        subprocess.run(
            ["git", "init", "--quiet", str(self.repo)],
            check=True,
            capture_output=True,
            text=True,
        )

    def tearDown(self):
        self.temporary_directory.cleanup()

    def run_helper(self, plan: Path) -> Path:
        result = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(SCRIPT),
                str(plan),
            ],
            cwd=self.repo,
            check=True,
            capture_output=True,
            text=True,
        )
        return Path(result.stdout.strip())

    def test_creates_plan_scoped_workspace_and_ignore_file(self):
        plan = self.repo / "docs" / "plans" / "example.md"
        plan.parent.mkdir(parents=True)
        plan.write_text("# Example\n", encoding="utf-8")

        workspace = self.run_helper(plan)

        self.assertEqual(workspace.resolve(), (self.repo / ".superpowers" / "sdd" / "example").resolve())
        self.assertEqual((workspace / "plan-path").read_text(encoding="utf-8").strip(), "docs/plans/example.md")
        self.assertEqual((workspace.parent / ".gitignore").read_text(encoding="utf-8"), "*\n")

    def test_disambiguates_colliding_plan_basenames(self):
        alpha = self.repo / "docs" / "alpha" / "plan.md"
        beta = self.repo / "docs" / "beta" / "plan.md"
        alpha.parent.mkdir(parents=True)
        beta.parent.mkdir(parents=True)
        alpha.write_text("# Alpha\n", encoding="utf-8")
        beta.write_text("# Beta\n", encoding="utf-8")

        first = self.run_helper(alpha)
        second = self.run_helper(beta)
        repeated = self.run_helper(beta)

        self.assertEqual(first.name, "plan")
        self.assertEqual(second.name, "plan-beta")
        self.assertEqual(repeated, second)
        self.assertEqual((second / "plan-path").read_text(encoding="utf-8").strip(), "docs/beta/plan.md")


if __name__ == "__main__":
    unittest.main()
