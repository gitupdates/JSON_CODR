import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from web_app.github_cli import GitHubCLI, GitHubCLIError


class GitHubCLITests(unittest.TestCase):
    def test_status_and_repository_listing_use_the_active_cli_identity(self):
        calls = []

        def runner(arguments, **kwargs):
            calls.append(arguments)
            output = (
                {"login": "gitupdates", "html_url": "https://github.com/gitupdates"}
                if arguments[-1] == "user"
                else [[{
                    "name": "sample",
                    "full_name": "gitupdates/sample",
                    "private": True,
                    "html_url": "https://github.com/gitupdates/sample",
                    "default_branch": "main",
                    "permissions": {"push": True},
                }]]
            )
            return subprocess.CompletedProcess(arguments, 0, json.dumps(output), "")

        client = GitHubCLI(executable_finder=lambda name: f"{name}.exe", runner=runner)

        self.assertEqual(client.status()["login"], "gitupdates")
        repositories = client.repositories()
        self.assertEqual(repositories[0]["full_name"], "gitupdates/sample")
        self.assertEqual(repositories[0]["permissions"], {"push": True})
        self.assertEqual(len(calls), 2)
        self.assertTrue(all(call[0] == "gh.exe" for call in calls))

    def test_issue_reads_filter_pull_requests_and_create_uses_safe_argument_list(self):
        calls = []

        def runner(arguments, **kwargs):
            calls.append(arguments)
            if "--paginate" in arguments:
                output = [[
                    {"number": 7, "title": "Issue", "state": "open"},
                    {"number": 8, "title": "Pull request", "pull_request": {"url": "https://api.github.com"}},
                ]]
            else:
                output = {"number": 9, "title": "Created"}
            return subprocess.CompletedProcess(arguments, 0, json.dumps(output), "")

        client = GitHubCLI(executable_finder=lambda name: f"{name}.exe", runner=runner)
        issues = client.issues("gitupdates", "sample")
        title = "title; this is still data"
        created = client.create_issue("gitupdates", "sample", title, "$(not-a-shell-command)")

        self.assertEqual([item["number"] for item in issues], [7])
        self.assertEqual(created["number"], 9)
        self.assertIn(f"title={title}", calls[1])
        self.assertIn("body=$(not-a-shell-command)", calls[1])

    def test_branch_and_commit_reads_return_only_public_summary_fields(self):
        def runner(arguments, **kwargs):
            if "/commits?" in arguments[-1]:
                output = [[{
                    "sha": "abc123",
                    "html_url": "https://github.com/gitupdates/sample/commit/abc123",
                    "commit": {
                        "message": "A commit\nwith details",
                        "author": {"name": "Test User", "date": "2025-01-01T00:00:00Z"},
                    },
                    "author": {"login": "test-user"},
                }]]
            else:
                output = [[{"name": "main", "protected": True, "commit": {"sha": "ignored"}}]]
            return subprocess.CompletedProcess(arguments, 0, json.dumps(output), "")

        client = GitHubCLI(executable_finder=lambda name: f"{name}.exe", runner=runner)

        self.assertEqual(
            client.branches("gitupdates", "sample"),
            [{"name": "main", "protected": True, "sha": "ignored"}],
        )
        commits = client.commits("gitupdates", "sample")
        self.assertEqual(commits[0]["sha"], "abc123")
        self.assertEqual(commits[0]["message"], "A commit\nwith details")
        self.assertNotIn("login", commits[0]["author"])

    def test_authentication_errors_are_mapped_and_credentials_redacted(self):
        def runner(arguments, **kwargs):
            return subprocess.CompletedProcess(
                arguments, 1, "", "HTTP 401: authentication failed with ghp_123456789012345678901234567890"
            )

        client = GitHubCLI(executable_finder=lambda name: f"{name}.exe", runner=runner)
        with self.assertRaises(GitHubCLIError) as raised:
            client.status()
        self.assertEqual(raised.exception.status_code, 401)
        self.assertNotIn("ghp_", str(raised.exception))

    def test_local_branch_stage_commit_and_push_are_scoped_to_github_origin(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            subprocess.run(["git", "init", "-b", "main"], cwd=root, check=True, capture_output=True)
            subprocess.run(["git", "config", "user.name", "Test User"], cwd=root, check=True)
            subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=root, check=True)
            subprocess.run(
                ["git", "remote", "add", "origin", "https://github.com/gitupdates/sample.git"],
                cwd=root,
                check=True,
            )
            (root / "README.md").write_text("initial\n", encoding="utf-8")
            subprocess.run(["git", "add", "README.md"], cwd=root, check=True)
            subprocess.run(["git", "commit", "-m", "initial"], cwd=root, check=True, capture_output=True)
            (root / "README.md").write_text("updated\n", encoding="utf-8")

            calls = []

            def runner(arguments, **kwargs):
                calls.append(arguments)
                if Path(arguments[0]).name == "gh.exe":
                    return subprocess.CompletedProcess(arguments, 0, '{"permissions":{"push":true}}', "")
                if "push" in arguments:
                    return subprocess.CompletedProcess(arguments, 0, "pushed", "")
                return subprocess.run(arguments, **kwargs)

            client = GitHubCLI(
                executable_finder=lambda name: f"{name}.exe" if name == "gh" else shutil.which(name),
                runner=runner,
            )
            self.assertEqual(client.local_status(str(root))["repository"], "gitupdates/sample")
            branch = client.create_local_branch(str(root), "feature/github-support")
            self.assertEqual(branch["branch"], "feature/github-support")
            staged = client.stage_local_files(str(root), ["README.md"])
            self.assertEqual(staged["staged_paths"], ["README.md"])
            committed = client.commit_local_changes(str(root), "Update README")
            self.assertTrue(committed["commit"])
            pushed = client.push_local_changes(str(root))

            self.assertEqual(pushed["status"], "pushed")
            self.assertTrue(any("push" in arguments for arguments in calls))

    def test_local_fetch_and_pull_report_tracking_and_block_unsafe_pulls(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory) / "project"
            root.mkdir()
            subprocess.run(["git", "init", "-b", "main"], cwd=root, check=True, capture_output=True)
            subprocess.run(["git", "config", "user.name", "Test User"], cwd=root, check=True)
            subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=root, check=True)
            subprocess.run(
                ["git", "remote", "add", "origin", "https://github.com/gitupdates/sample.git"],
                cwd=root,
                check=True,
            )
            (root / "README.md").write_text("initial\n", encoding="utf-8")
            subprocess.run(["git", "add", "README.md"], cwd=root, check=True)
            subprocess.run(["git", "commit", "-m", "initial"], cwd=root, check=True, capture_output=True)

            calls = []
            counts = ["1\t1\n"]

            def runner(arguments, **kwargs):
                calls.append(arguments)
                if "fetch" in arguments:
                    return subprocess.CompletedProcess(arguments, 0, "", "")
                if "--porcelain=v2" in arguments:
                    return subprocess.CompletedProcess(
                        arguments, 0,
                        "# branch.oid abc123\n# branch.head main\n# branch.upstream origin/main\n# branch.ab +1 -1\n",
                        "",
                    )
                if "ls-remote" in arguments:
                    return subprocess.CompletedProcess(arguments, 0, "abc123\trefs/heads/main\n", "")
                if "rev-list" in arguments:
                    return subprocess.CompletedProcess(arguments, 0, counts[0], "")
                if "merge" in arguments:
                    return subprocess.CompletedProcess(arguments, 0, "", "")
                if Path(arguments[0]).name == "gh.exe":
                    return subprocess.CompletedProcess(arguments, 0, '{"permissions":{"push":true}}', "")
                return subprocess.run(arguments, **kwargs)

            client = GitHubCLI(
                executable_finder=lambda name: f"{name}.exe" if name == "gh" else shutil.which(name),
                runner=runner,
            )

            fetched = client.fetch_local_changes(str(root))
            self.assertEqual((fetched["ahead"], fetched["behind"]), (1, 1))
            self.assertEqual(fetched["remote_branch"], "origin/main")
            with self.assertRaisesRegex(ValueError, "diverged"):
                client.pull_local_changes(str(root))
            self.assertFalse(any("merge" in arguments for arguments in calls))

            counts[0] = "0\t1\n"
            pulled = client.pull_local_changes(str(root))
            self.assertEqual(pulled["status"], "pulled")
            self.assertTrue(any("merge" in arguments and "--ff-only" in arguments for arguments in calls))

            (root / "README.md").write_text("uncommitted\n", encoding="utf-8")
            fetch_count = sum("fetch" in arguments for arguments in calls)
            with self.assertRaisesRegex(ValueError, "local changes"):
                client.pull_local_changes(str(root))
            self.assertEqual(sum("fetch" in arguments for arguments in calls), fetch_count)

    def test_clone_uses_gh_and_requires_new_absolute_destination(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            destination = root / "clone"
            calls = []

            def runner(arguments, **kwargs):
                calls.append(arguments)
                if Path(arguments[0]).name == "gh.exe":
                    self.assertEqual(arguments[1:4], ["repo", "clone", "gitupdates/sample"])
                    target = Path(arguments[4])
                    target.mkdir()
                    subprocess.run(["git", "init", "-b", "main"], cwd=target, check=True, capture_output=True)
                    subprocess.run(
                        ["git", "remote", "add", "origin", "https://github.com/gitupdates/sample.git"],
                        cwd=target,
                        check=True,
                    )
                    return subprocess.CompletedProcess(arguments, 0, "Cloned\n", "")
                return subprocess.run(arguments, **kwargs)

            client = GitHubCLI(
                executable_finder=lambda name: f"{name}.exe" if name == "gh" else shutil.which(name),
                runner=runner,
            )
            result = client.clone_local_repository("gitupdates/sample", str(destination))
            self.assertEqual(result["repository"], "gitupdates/sample")
            self.assertEqual(result["status"], "cloned")
            self.assertEqual(calls[0][1:4], ["repo", "clone", "gitupdates/sample"])
            with self.assertRaisesRegex(ValueError, "must not already exist"):
                client.clone_local_repository("gitupdates/sample", str(destination))
            with self.assertRaisesRegex(ValueError, "absolute"):
                client.clone_local_repository("gitupdates/sample", "relative/path")

    def test_repository_branch_and_release_lifecycle_use_gh_api(self):
        calls = []

        def runner(arguments, **kwargs):
            calls.append(arguments)
            target = next(
                (argument for argument in arguments if argument.startswith(("repos/", "orgs/"))),
                arguments[-1],
            )
            if target == "orgs/example/repos":
                output = {"name": "new-project", "full_name": "example/new-project", "private": True}
            elif target == "repos/example/new-project":
                output = {"name": "renamed", "full_name": "example/renamed", "archived": True}
            elif target.endswith("/git/ref/heads/main"):
                output = {"object": {"sha": "abc123"}}
            elif target.endswith("/git/refs"):
                output = {"ref": "refs/heads/feature/change"}
            elif "releases?per_page=" in target:
                output = [[{"id": 7, "tag_name": "v1", "name": "First", "body": "Notes"}]]
            elif target.endswith("/releases/7") and "PATCH" in arguments:
                output = {"id": 7, "tag_name": "v1", "name": "Updated"}
            elif "DELETE" in arguments:
                output = ""
            else:
                output = {}
            return subprocess.CompletedProcess(arguments, 0, json.dumps(output) if output else "", "")

        client = GitHubCLI(executable_finder=lambda name: f"{name}.exe", runner=runner)
        created = client.create_repository("new-project", "Description", True, True, "example")
        updated = client.update_repository("example", "new-project", {"name": "renamed", "archived": True})
        deleted = client.delete_repository("example", "renamed")
        branch = client.create_branch("example", "renamed", "feature/change", "main")
        removed_branch = client.delete_branch("example", "renamed", "feature/change")
        releases = client.releases("example", "renamed")
        updated_release = client.update_release("example", "renamed", 7, {"name": "Updated"})
        deleted_release = client.delete_release("example", "renamed", 7)

        self.assertEqual(created["full_name"], "example/new-project")
        self.assertEqual(updated["full_name"], "example/renamed")
        self.assertTrue(deleted["deleted"])
        self.assertEqual(branch["sha"], "abc123")
        self.assertTrue(removed_branch["deleted"])
        self.assertEqual(releases[0]["id"], 7)
        self.assertEqual(releases[0]["tag_name"], "v1")
        self.assertEqual(updated_release["name"], "Updated")
        self.assertTrue(deleted_release["deleted"])
        self.assertTrue(any("orgs/example/repos" in call for call in calls))
        self.assertTrue(any("DELETE" in call and "repos/example/renamed" in call[-1] for call in calls))

    def test_invalid_repo_and_git_paths_fail_before_remote_actions(self):
        client = GitHubCLI(executable_finder=lambda _name: None)
        with self.assertRaises(ValueError):
            client.issues("../owner", "repo")
        with self.assertRaises(ValueError):
            GitHubCLI._relative_path("../outside")
        with self.assertRaises(GitHubCLIError):
            client.status()


if __name__ == "__main__":
    unittest.main()
