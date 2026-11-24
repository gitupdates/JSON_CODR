import json
import shutil
import subprocess
import tempfile
import threading
import unittest
from pathlib import Path

from web_app.github_cli import GitHubBuildConflict, GitHubCLI, GitHubCLIError, PublicationReceipt


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
        calls = []

        def runner(arguments, **kwargs):
            calls.append(arguments)
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
        filtered_commits = client.commits("gitupdates", "sample", "feature/ui")
        self.assertEqual(commits[0]["sha"], "abc123")
        self.assertEqual(filtered_commits[0]["sha"], "abc123")
        self.assertEqual(commits[0]["message"], "A commit\nwith details")
        self.assertNotIn("login", commits[0]["author"])
        self.assertEqual(calls[1][-1], "repos/gitupdates/sample/commits?per_page=30")
        self.assertEqual(calls[2], ["git.exe", "check-ref-format", "refs/heads/feature/ui"])
        self.assertEqual(calls[3][-1], "repos/gitupdates/sample/commits?per_page=30&sha=feature%2Fui")

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

    def test_selected_build_comparison_classifies_safe_and_blocked_states(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory).resolve()
            state = {
                "repository": "example/sample",
                "branch": "main",
                "local_sha": "a" * 40,
                "remote_sha": "b" * 40,
                "ahead": 0,
                "behind": 1,
                "dirty": False,
                "remote_exists": True,
            }
            calls = []

            def runner(arguments, **kwargs):
                calls.append(arguments)
                if arguments[1:4] == ["api", "--hostname", "github.com"] and arguments[-1] == "user":
                    return subprocess.CompletedProcess(arguments, 0, '{"login":"octocat","html_url":"https://github.com/octocat"}', "")
                if arguments[1:3] == ["check-ref-format", "refs/heads/main"]:
                    return subprocess.CompletedProcess(arguments, 0, "", "")
                command = arguments[3:]
                if command == ["rev-parse", "--show-toplevel"]:
                    output = str(root)
                elif command == ["remote", "get-url", "origin"]:
                    output = f"https://github.com/{state['repository']}.git"
                elif command == ["branch", "--show-current"]:
                    output = state["branch"]
                elif command == ["status", "--porcelain", "--untracked-files=normal"]:
                    output = " M README.md" if state["dirty"] else ""
                elif command[:3] == ["ls-remote", "--heads", "origin"]:
                    output = f"{state['remote_sha']}\trefs/heads/main\n" if state["remote_exists"] else ""
                elif command[:2] == ["fetch", "origin"]:
                    output = ""
                elif command == ["rev-parse", "HEAD"]:
                    output = state["local_sha"]
                elif command == ["rev-parse", "refs/remotes/origin/main"]:
                    output = state["remote_sha"]
                elif command[:3] == ["rev-list", "--left-right", "--count"]:
                    output = f"{state['ahead']}\t{state['behind']}"
                elif command[:3] == ["show", "-s", "--format=%H%x00%h%x00%s%x00%an%x00%aI"]:
                    sha = state["local_sha"] if command[3] == "HEAD" else state["remote_sha"]
                    output = f"{sha}\x00{sha[:7]}\x00Test subject\x00Test Author\x002026-11-21T10:00:00-06:00"
                elif command == ["status", "--porcelain=v2", "--branch"]:
                    output = f"# branch.oid {state['local_sha']}\n# branch.head {state['branch']}\n"
                else:
                    raise AssertionError(f"Unexpected command: {arguments}")
                return subprocess.CompletedProcess(arguments, 0, output, "")

            client = GitHubCLI(
                executable_finder=lambda name: f"{name}.exe",
                runner=runner,
            )
            behind = client.check_build(str(root), "example/sample", "main")
            self.assertEqual((behind["status"], behind["ahead"], behind["behind"]), ("behind", 0, 1))
            self.assertTrue(behind["update_allowed"])
            self.assertEqual(behind["local_commit"]["sha"], "a" * 40)
            self.assertEqual(behind["remote_commit"]["sha"], "b" * 40)
            self.assertIsNone(behind["upstream"])
            self.assertIn(
                "+refs/heads/main:refs/remotes/origin/main",
                next(call for call in calls if "fetch" in call),
            )

            state["dirty"] = True
            self.assertEqual(client.check_build(str(root), "example/sample", "main")["status"], "local_changes")
            state.update(dirty=False, ahead=1, behind=0)
            self.assertEqual(client.check_build(str(root), "example/sample", "main")["status"], "ahead")
            state.update(ahead=1, behind=1)
            self.assertEqual(client.check_build(str(root), "example/sample", "main")["status"], "diverged")
            state.update(ahead=0, behind=1, branch="feature/other")
            self.assertEqual(client.check_build(str(root), "example/sample", "main")["status"], "branch_mismatch")
            state.update(branch="main", repository="example/other")
            self.assertEqual(client.check_build(str(root), "example/sample", "main")["status"], "repository_mismatch")
            state.update(repository="example/sample", branch="")
            self.assertEqual(client.check_build(str(root), "example/sample", "main")["status"], "detached")
            state.update(branch="main", remote_exists=False)
            self.assertEqual(client.check_build(str(root), "example/sample", "main")["status"], "remote_missing")

    def test_selected_build_update_revalidates_observed_shas_and_fast_forwards_only(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory).resolve()
            local_sha = "a" * 40
            remote_sha = "b" * 40
            state = {"local_sha": local_sha, "remote_sha": remote_sha, "dirty": False}
            calls = []

            def runner(arguments, **kwargs):
                calls.append(arguments)
                if arguments[1:4] == ["api", "--hostname", "github.com"] and arguments[-1] == "user":
                    return subprocess.CompletedProcess(arguments, 0, '{"login":"octocat","html_url":"https://github.com/octocat"}', "")
                if arguments[1:3] == ["check-ref-format", "refs/heads/main"]:
                    return subprocess.CompletedProcess(arguments, 0, "", "")
                command = arguments[3:]
                outputs = {
                    ("rev-parse", "--show-toplevel"): str(root),
                    ("remote", "get-url", "origin"): "https://github.com/example/sample.git",
                    ("branch", "--show-current"): "main",
                    ("status", "--porcelain", "--untracked-files=normal"): " M file" if state["dirty"] else "",
                    ("ls-remote", "--heads", "origin", "refs/heads/main"): f"{state['remote_sha']}\trefs/heads/main\n",
                    ("fetch", "origin", "+refs/heads/main:refs/remotes/origin/main"): "",
                    ("rev-parse", "HEAD"): state["local_sha"],
                    ("rev-parse", "refs/remotes/origin/main"): state["remote_sha"],
                    ("rev-list", "--left-right", "--count", "HEAD...refs/remotes/origin/main"): (
                        "0\t0" if state["local_sha"] == state["remote_sha"] else "0\t1"
                    ),
                    ("status", "--porcelain=v2", "--branch"): "# branch.head main\n",
                }
                key = tuple(command)
                if command[:3] == ["show", "-s", "--format=%H%x00%h%x00%s%x00%an%x00%aI"]:
                    sha = state["local_sha"] if command[3] == "HEAD" else state["remote_sha"]
                    output = f"{sha}\x00{sha[:7]}\x00Build\x00Builder\x002026-11-21T10:00:00-06:00"
                elif key == ("merge", "--ff-only", remote_sha):
                    state["local_sha"] = state["remote_sha"]
                    output = "Fast-forward"
                elif key in outputs:
                    output = outputs[key]
                else:
                    raise AssertionError(f"Unexpected command: {arguments}")
                return subprocess.CompletedProcess(arguments, 0, output, "")

            client = GitHubCLI(executable_finder=lambda name: f"{name}.exe", runner=runner)
            with self.assertRaises(GitHubBuildConflict):
                client.update_build(str(root), "example/sample", "main", "c" * 40, remote_sha, "octocat", "github.com")
            self.assertFalse(any("merge" in call for call in calls))

            updated = client.update_build(str(root), "example/sample", "main", local_sha, remote_sha, "octocat", "github.com")
            self.assertEqual(updated["status"], "current")
            self.assertFalse(updated["update_allowed"])
            self.assertTrue(any(call[-3:] == ["merge", "--ff-only", remote_sha] for call in calls))
            flattened = " ".join(part for call in calls for part in call)
            for forbidden in (" reset ", " clean ", " checkout ", " switch ", " rebase ", "--force", "--set-upstream"):
                self.assertNotIn(forbidden, f" {flattened} ")

            state.update(local_sha=local_sha, dirty=True)
            merge_count = sum("merge" in call for call in calls)
            with self.assertRaises(GitHubBuildConflict):
                client.update_build(str(root), "example/sample", "main", local_sha, remote_sha, "octocat", "github.com")
            self.assertEqual(sum("merge" in call for call in calls), merge_count)

    def test_dot_prefixed_repository_name_is_valid(self):
        client = GitHubCLI(executable_finder=lambda name: "git.exe")
        self.assertEqual(client._validated_repository("example/.github"), "example/.github")

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
            elif target == "repos/example/renamed" and "GET" in arguments:
                output = {"default_branch": "main"}
            elif target.endswith("/branches/feature/change"):
                output = {"name": "feature/change", "protected": False}
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


class GitHubPublicationTests(unittest.TestCase):
    def _repository(self, root: Path):
        remote = root / "remote.git"
        project = root / "candidate"
        subprocess.run(["git", "init", "--bare", str(remote)], cwd=root, check=True, capture_output=True)
        project.mkdir()
        subprocess.run(["git", "init", "-b", "main"], cwd=project, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.name", "Candidate"], cwd=project, check=True)
        subprocess.run(["git", "config", "user.email", "candidate@example.invalid"], cwd=project, check=True)
        (project / "README.md").write_text("initial\n", encoding="utf-8")
        subprocess.run(["git", "add", "README.md"], cwd=project, check=True)
        subprocess.run(["git", "commit", "-m", "initial"], cwd=project, check=True, capture_output=True)
        subprocess.run(["git", "remote", "add", "origin", str(remote)], cwd=project, check=True)
        subprocess.run(["git", "push", "-u", "origin", "main"], cwd=project, check=True, capture_output=True)
        initial = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=project, check=True, capture_output=True, text=True
        ).stdout.strip()
        (project / "candidate.txt").write_text("candidate\n", encoding="utf-8")
        subprocess.run(["git", "add", "candidate.txt"], cwd=project, check=True)
        subprocess.run(["git", "commit", "-m", "candidate"], cwd=project, check=True, capture_output=True)
        candidate = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=project, check=True, capture_output=True, text=True
        ).stdout.strip()
        return project, remote, initial, candidate

    def _client(self, runner=subprocess.run):
        return GitHubCLI(executable_finder=shutil.which, runner=runner)

    def test_publish_verified_uses_exact_sha_lease_and_duplicate_is_reconciled(self):
        """The push must use an exact expected-SHA lease, never a blind force."""
        with tempfile.TemporaryDirectory() as directory:
            project, remote, initial, candidate = self._repository(Path(directory))
            calls = []

            def runner(arguments, **kwargs):
                calls.append(list(arguments))
                return subprocess.run(arguments, **kwargs)

            client = self._client(runner)
            first = client.publish_verified(str(project), "main", candidate, initial)
            repeated = client.publish_verified(str(project), "main", candidate, initial)

            self.assertIsInstance(first, PublicationReceipt)
            self.assertEqual(first.commit_sha, candidate)
            self.assertEqual(repeated.status, "already_published")
            pushes = [call for call in calls if "push" in call]
            self.assertEqual(len(pushes), 1)
            self.assertIn(f"{candidate}:refs/heads/main", pushes[0])
            self.assertIn(f"--force-with-lease=refs/heads/main:{initial}", pushes[0])
            self.assertFalse(any(argument == "--force" for call in calls for argument in call))
            remote_sha = subprocess.run(
                ["git", "rev-parse", "main"], cwd=remote, check=True, capture_output=True, text=True
            ).stdout.strip()
            self.assertEqual(remote_sha, candidate)

    def test_expected_sha_lease_rejects_remote_race_between_check_and_push(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project, remote, initial, candidate = self._repository(root)
            publisher = root / "publisher"
            subprocess.run(["git", "clone", "-b", "main", str(remote), str(publisher)], check=True, capture_output=True)
            subprocess.run(["git", "config", "user.name", "Remote"], cwd=publisher, check=True)
            subprocess.run(["git", "config", "user.email", "remote@example.invalid"], cwd=publisher, check=True)
            raced = False

            def runner(arguments, **kwargs):
                nonlocal raced
                if "push" in arguments and not raced:
                    raced = True
                    (publisher / "remote.txt").write_text("race\n", encoding="utf-8")
                    subprocess.run(["git", "add", "remote.txt"], cwd=publisher, check=True)
                    subprocess.run(["git", "commit", "-m", "remote race"], cwd=publisher, check=True, capture_output=True)
                    subprocess.run(["git", "push", "origin", "HEAD:main"], cwd=publisher, check=True, capture_output=True)
                return subprocess.run(arguments, **kwargs)

            with self.assertRaises(GitHubBuildConflict):
                self._client(runner).publish_verified(str(project), "main", candidate, initial)
            self.assertEqual(
                subprocess.run(
                    ["git", "show", "main:remote.txt"], cwd=remote, check=True,
                    capture_output=True, text=True,
                ).stdout,
                "race\n",
            )

    def test_remote_drift_and_divergence_are_rejected_before_push(self):
        """Ignoring the observed remote SHA or ancestry must fail this test."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project, remote, initial, candidate = self._repository(root)
            publisher = root / "publisher"
            subprocess.run(["git", "clone", "-b", "main", str(remote), str(publisher)], check=True, capture_output=True)
            subprocess.run(["git", "config", "user.name", "Remote"], cwd=publisher, check=True)
            subprocess.run(["git", "config", "user.email", "remote@example.invalid"], cwd=publisher, check=True)
            (publisher / "remote.txt").write_text("remote\n", encoding="utf-8")
            subprocess.run(["git", "add", "remote.txt"], cwd=publisher, check=True)
            subprocess.run(["git", "commit", "-m", "remote"], cwd=publisher, check=True, capture_output=True)
            subprocess.run(["git", "push", "origin", "HEAD:main"], cwd=publisher, check=True, capture_output=True)
            advanced = subprocess.run(
                ["git", "rev-parse", "HEAD"], cwd=publisher, check=True, capture_output=True, text=True
            ).stdout.strip()
            client = self._client()

            with self.assertRaisesRegex(GitHubBuildConflict, "remote.*changed|drift"):
                client.publish_verified(str(project), "main", candidate, initial)
            with self.assertRaisesRegex(GitHubBuildConflict, "descend|diverg"):
                client.publish_verified(str(project), "main", candidate, advanced)
            self.assertEqual(
                subprocess.run(
                    ["git", "rev-parse", "main"], cwd=remote, check=True,
                    capture_output=True, text=True,
                ).stdout.strip(),
                advanced,
            )

    def test_ambiguous_network_success_is_reconciled_by_remote_commit(self):
        """Reporting a failed publication after the remote accepted it must fail this test."""
        with tempfile.TemporaryDirectory() as directory:
            project, _, initial, candidate = self._repository(Path(directory))

            def ambiguous_runner(arguments, **kwargs):
                result = subprocess.run(arguments, **kwargs)
                if "push" in arguments:
                    return subprocess.CompletedProcess(arguments, 1, result.stdout, "connection reset")
                return result

            receipt = self._client(ambiguous_runner).publish_verified(
                str(project), "main", candidate, initial
            )
            self.assertEqual(receipt.status, "published")
            self.assertTrue(receipt.reconciled)
            self.assertEqual(receipt.observed_remote_sha, candidate)

    def test_publication_reconciliation_survives_a_fresh_publisher_process(self):
        with tempfile.TemporaryDirectory() as directory:
            project, _, initial, candidate = self._repository(Path(directory))
            self._client().publish_verified(str(project), "main", candidate, initial)

            state = self._client().reconcile_publication(
                "main", candidate, project_root=str(project)
            )

            self.assertEqual(state.status, "published")
            self.assertEqual(state.remote_sha, candidate)

    def test_concurrent_publish_attempt_is_rejected_by_os_visible_lock(self):
        """A per-instance threading lock would allow both clients into the push window."""
        with tempfile.TemporaryDirectory() as directory:
            project, _, initial, candidate = self._repository(Path(directory))
            entered = threading.Event()
            release = threading.Event()
            failures = []

            def blocking_runner(arguments, **kwargs):
                if "push" in arguments:
                    entered.set()
                    release.wait(5)
                return subprocess.run(arguments, **kwargs)

            def publish():
                try:
                    self._client(blocking_runner).publish_verified(
                        str(project), "main", candidate, initial
                    )
                except Exception as error:  # pragma: no cover - surfaced below
                    failures.append(error)

            thread = threading.Thread(target=publish)
            thread.start()
            self.assertTrue(entered.wait(5))
            try:
                with self.assertRaisesRegex(GitHubBuildConflict, "already in progress"):
                    self._client().publish_verified(str(project), "main", candidate, initial)
            finally:
                release.set()
                thread.join(5)
            self.assertEqual(failures, [])


if __name__ == "__main__":
    unittest.main()
