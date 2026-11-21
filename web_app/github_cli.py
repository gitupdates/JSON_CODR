from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Callable, Literal
from urllib.parse import quote, urlencode, urlparse


class GitHubCLIError(RuntimeError):
    def __init__(self, message: str, status_code: int = 502) -> None:
        super().__init__(message)
        self.status_code = status_code


class GitHubCLI:
    def __init__(
        self,
        executable_finder: Callable[[str], str | None] = shutil.which,
        runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
        timeout: int = 30,
    ) -> None:
        self._executable_finder = executable_finder
        self._runner = runner
        self._timeout = timeout

    def status(self) -> dict[str, object]:
        user = self._json("gh", ["api", "user"])
        if not isinstance(user, dict):
            raise GitHubCLIError("GitHub CLI returned an invalid user")
        login = user.get("login")
        if not isinstance(login, str) or not login:
            raise GitHubCLIError("GitHub CLI returned a user without a login")
        return {
            "authenticated": True,
            "login": login,
            "url": user.get("html_url"),
            "credential_source": "local GitHub CLI",
        }

    def repositories(self) -> list[dict[str, object]]:
        pages = self._api_pages(
            "user/repos",
            {
                "per_page": "100",
                "visibility": "all",
                "affiliation": "owner,collaborator,organization_member",
            },
        )
        return [
            {
                "name": item.get("name"),
                "full_name": item.get("full_name"),
                "description": item.get("description"),
                "private": bool(item.get("private")),
                "archived": bool(item.get("archived")),
                "visibility": item.get("visibility"),
                "homepage": item.get("homepage"),
                "url": item.get("html_url"),
                "default_branch": item.get("default_branch"),
                "permissions": item.get("permissions") or {},
            }
            for item in pages
            if isinstance(item, dict)
        ]

    def issues(self, owner: str, repository: str, state: Literal["open", "closed", "all"] = "open"):
        path = self._repository_path(owner, repository)
        items = self._api_pages(
            f"{path}/issues",
            {"state": state, "per_page": "100", "sort": "updated", "direction": "desc"},
        )
        return [self._summary(item) for item in items if isinstance(item, dict) and "pull_request" not in item]

    def pull_requests(self, owner: str, repository: str, state: Literal["open", "closed", "all"] = "open"):
        path = self._repository_path(owner, repository)
        items = self._api_pages(
            f"{path}/pulls",
            {"state": state, "per_page": "100", "sort": "updated", "direction": "desc"},
        )
        return [self._summary(item) for item in items if isinstance(item, dict)]

    def branches(self, owner: str, repository: str) -> list[dict[str, object]]:
        path = self._repository_path(owner, repository)
        items = self._api_pages(f"{path}/branches", {"per_page": "100"})
        return [
            {
                "name": item.get("name"),
                "protected": item.get("protected"),
                "sha": (item.get("commit") or {}).get("sha"),
            }
            for item in items
            if isinstance(item, dict)
        ]

    def create_branch(
        self, owner: str, repository: str, branch: str, source_branch: str,
    ) -> dict[str, object]:
        path = self._repository_path(owner, repository)
        branch = self._validated_branch(branch)
        source_branch = self._validated_branch(source_branch)
        source = self._api("GET", f"{path}/git/ref/heads/{quote(source_branch, safe='/')}")
        source_object = source.get("object")
        sha = source_object.get("sha") if isinstance(source_object, dict) else None
        if not isinstance(sha, str) or not sha:
            raise GitHubCLIError("GitHub did not return a source branch commit")
        self._api("POST", f"{path}/git/refs", {"ref": f"refs/heads/{branch}", "sha": sha})
        return {"repository": f"{owner}/{repository}", "branch": branch, "sha": sha}

    def delete_branch(self, owner: str, repository: str, branch: str) -> dict[str, object]:
        path = self._repository_path(owner, repository)
        branch = self._validated_branch(branch)
        details = self._api("GET", path)
        if details.get("default_branch") == branch:
            raise ValueError("The default branch cannot be deleted")
        branch_details = self._api("GET", f"{path}/branches/{quote(branch, safe='/')}")
        if branch_details.get("protected") is True:
            raise ValueError("Protected branches cannot be deleted")
        self._delete_api(f"{path}/git/refs/heads/{quote(branch, safe='/')}")
        return {"repository": f"{owner}/{repository}", "branch": branch, "deleted": True}

    def commits(
        self, owner: str, repository: str, branch: str | None = None,
    ) -> list[dict[str, object]]:
        path = self._repository_path(owner, repository)
        query = {"per_page": "30"}
        if branch is not None:
            query["sha"] = self._validated_branch(branch)
        items = self._api_pages(f"{path}/commits", query)
        commits = []
        for item in items:
            if not isinstance(item, dict):
                continue
            commit = item.get("commit")
            commit_data = commit if isinstance(commit, dict) else {}
            commits.append({
                "sha": item.get("sha"),
                "url": item.get("html_url"),
                "message": commit_data.get("message"),
                "author": commit_data.get("author"),
            })
        return commits

    def releases(self, owner: str, repository: str):
        path = self._repository_path(owner, repository)
        items = self._api_pages(f"{path}/releases", {"per_page": "100"})
        return [self._release_summary(item) for item in items if isinstance(item, dict)]

    def create_repository(
        self,
        name: str,
        description: str,
        private: bool,
        auto_init: bool,
        owner: str | None = None,
        homepage: str | None = None,
    ) -> dict[str, object]:
        if owner:
            path = f"orgs/{self._validated_owner(owner)}/repos"
        else:
            path = "user/repos"
        fields: dict[str, object] = {
            "name": name,
            "description": description,
            "private": private,
            "auto_init": auto_init,
        }
        if homepage:
            fields["homepage"] = homepage
        created = self._api("POST", path, fields)
        return self._repository_summary(created)

    def update_repository(self, owner: str, repository: str, fields: dict[str, object]) -> dict[str, object]:
        updated = self._api("PATCH", self._repository_path(owner, repository), fields)
        return self._repository_summary(updated)

    def delete_repository(self, owner: str, repository: str) -> dict[str, object]:
        full_name = f"{owner}/{repository}"
        self._delete_api(self._repository_path(owner, repository))
        return {"full_name": full_name, "deleted": True}

    def create_issue(self, owner: str, repository: str, title: str, body: str):
        return self._api(
            "POST",
            f"{self._repository_path(owner, repository)}/issues",
            {"title": title, "body": body},
        )

    def update_issue(self, owner: str, repository: str, number: int, fields: dict[str, object]):
        return self._api(
            "PATCH",
            f"{self._repository_path(owner, repository)}/issues/{self._number(number)}",
            fields,
        )

    def comment_issue(self, owner: str, repository: str, number: int, body: str):
        return self._api(
            "POST",
            f"{self._repository_path(owner, repository)}/issues/{self._number(number)}/comments",
            {"body": body},
        )

    def create_pull_request(
        self, owner: str, repository: str, head: str, base: str, title: str, body: str, draft: bool,
    ):
        return self._api(
            "POST",
            f"{self._repository_path(owner, repository)}/pulls",
            {"head": head, "base": base, "title": title, "body": body, "draft": draft},
        )

    def update_pull_request(self, owner: str, repository: str, number: int, fields: dict[str, object]):
        return self._api(
            "PATCH",
            f"{self._repository_path(owner, repository)}/pulls/{self._number(number)}",
            fields,
        )

    def merge_pull_request(
        self, owner: str, repository: str, number: int, method: Literal["merge", "squash", "rebase"],
    ):
        return self._api(
            "PUT",
            f"{self._repository_path(owner, repository)}/pulls/{self._number(number)}/merge",
            {"merge_method": method},
        )

    def create_release(
        self,
        owner: str,
        repository: str,
        tag_name: str,
        name: str,
        body: str,
        target_commitish: str | None,
        draft: bool,
        prerelease: bool,
    ):
        fields: dict[str, object] = {
            "tag_name": tag_name,
            "name": name,
            "body": body,
            "draft": draft,
            "prerelease": prerelease,
        }
        if target_commitish:
            fields["target_commitish"] = target_commitish
        return self._api("POST", f"{self._repository_path(owner, repository)}/releases", fields)

    def update_release(self, owner: str, repository: str, release_id: int, fields: dict[str, object]):
        if release_id < 1:
            raise ValueError("Release ID must be positive")
        return self._api(
            "PATCH",
            f"{self._repository_path(owner, repository)}/releases/{release_id}",
            fields,
        )

    def delete_release(self, owner: str, repository: str, release_id: int):
        if release_id < 1:
            raise ValueError("Release ID must be positive")
        self._delete_api(f"{self._repository_path(owner, repository)}/releases/{release_id}")
        return {"repository": f"{owner}/{repository}", "release_id": release_id, "deleted": True}

    def local_status(self, project_root: str) -> dict[str, object]:
        root, repository = self._local_repository(project_root)
        branch = self._git(root, "branch", "--show-current") or None
        staged = self._git_names(root, "diff", "--cached", "--name-only", "-z")
        unstaged = self._git_names(root, "diff", "--name-only", "-z")
        untracked = self._git_names(root, "ls-files", "--others", "--exclude-standard", "-z")
        statuses: dict[str, dict[str, object]] = {}
        for path in staged:
            statuses.setdefault(path, {"path": path})["staged"] = True
        for path in unstaged:
            statuses.setdefault(path, {"path": path})["unstaged"] = True
        for path in untracked:
            statuses.setdefault(path, {"path": path})["untracked"] = True
        return {
            "project_root": str(root),
            "repository": repository,
            "branch": branch,
            **self._tracking_status(root, branch),
            "changes": list(statuses.values()),
            "staged_paths": staged,
            "push_allowed": self._repository_permissions(*repository.split("/")).get("push") is True,
        }

    def create_local_branch(self, project_root: str, branch: str) -> dict[str, object]:
        root, repository = self._local_repository(project_root)
        if not branch or len(branch) > 200 or any(ord(char) < 32 for char in branch):
            raise ValueError("Branch name is invalid")
        self._git(root, "check-ref-format", "--branch", branch)
        self._git(root, "switch", "--create", branch)
        return {"project_root": str(root), "repository": repository, "branch": branch}

    def stage_local_files(self, project_root: str, paths: list[str]) -> dict[str, object]:
        root, _ = self._local_repository(project_root)
        if not paths or len(paths) > 100:
            raise ValueError("Select between 1 and 100 files to stage")
        normalized = [self._relative_path(path) for path in paths]
        available = set(self._git_names(root, "diff", "--name-only", "-z"))
        available.update(self._git_names(root, "diff", "--cached", "--name-only", "-z"))
        available.update(self._git_names(root, "ls-files", "--others", "--exclude-standard", "-z"))
        if not set(normalized).issubset(available):
            raise ValueError("Only changed, untracked, or already staged files can be staged")
        self._git(root, "--literal-pathspecs", "add", "--", *normalized)
        return self.local_status(str(root))

    def commit_local_changes(self, project_root: str, message: str) -> dict[str, object]:
        root, repository = self._local_repository(project_root)
        if not message.strip() or len(message) > 500 or any(ord(char) < 32 and char not in "\r\n\t" for char in message):
            raise ValueError("Commit message is invalid")
        staged = self._git_names(root, "diff", "--cached", "--name-only", "-z")
        if not staged:
            raise ValueError("Stage at least one file before committing")
        self._git(root, "commit", "-m", message.strip())
        commit = self._git(root, "rev-parse", "HEAD")
        return {"project_root": str(root), "repository": repository, "commit": commit, "files": staged}

    def push_local_changes(self, project_root: str) -> dict[str, object]:
        root, repository = self._local_repository(project_root)
        permissions = self._repository_permissions(*repository.split("/"))
        if permissions.get("push") is not True:
            raise PermissionError("The active GitHub account does not have push access to this repository")
        branch = self._git(root, "branch", "--show-current")
        if not branch:
            raise ValueError("Cannot push from a detached HEAD")
        self._git(root, "push", "--set-upstream", "origin", branch)
        return {"project_root": str(root), "repository": repository, "branch": branch, "status": "pushed"}

    def fetch_local_changes(self, project_root: str) -> dict[str, object]:
        root, repository = self._local_repository(project_root)
        self._git(root, "fetch", "origin")
        branch = self._git(root, "branch", "--show-current") or None
        return {
            "project_root": str(root),
            "repository": repository,
            "branch": branch,
            "status": "fetched",
            **self._tracking_status(root, branch),
        }

    def pull_local_changes(self, project_root: str) -> dict[str, object]:
        root, repository = self._local_repository(project_root)
        branch = self._git(root, "branch", "--show-current")
        if not branch:
            raise ValueError("Cannot pull from a detached HEAD")
        if self._git(root, "status", "--porcelain", "--untracked-files=normal"):
            raise ValueError("Commit or remove local changes before pulling")
        tracking = self._tracking_status(root, branch)
        remote_branch = tracking["remote_branch"]
        if not isinstance(remote_branch, str) or not remote_branch.startswith("origin/"):
            raise ValueError("Current branch must track an origin branch before pulling")
        remote_name = remote_branch.removeprefix("origin/")
        advertised = self._git(root, "ls-remote", "--heads", "origin", f"refs/heads/{remote_name}")
        if not advertised:
            raise ValueError(f"Remote branch {remote_branch} no longer exists")
        self._git(
            root,
            "fetch",
            "origin",
            f"+refs/heads/{remote_name}:refs/remotes/origin/{remote_name}",
        )
        remote_ref = f"refs/remotes/{remote_branch}"
        ahead, behind = self._ahead_behind(root, remote_ref)
        if ahead and behind:
            raise ValueError("Local and remote branches have diverged; reconcile them before pulling")
        if behind:
            self._git(root, "merge", "--ff-only", remote_ref)
            status = "pulled"
        else:
            status = "up_to_date"
        return {
            "project_root": str(root),
            "repository": repository,
            "branch": branch,
            "remote_branch": f"origin/{branch}",
            "ahead": ahead,
            "behind": behind,
            "status": status,
        }

    def clone_local_repository(self, repository: str, destination: str) -> dict[str, object]:
        parts = repository.split("/")
        if len(parts) != 2:
            raise ValueError("Repository must use the owner/repository format")
        full_name = self._repository_path(parts[0], parts[1]).removeprefix("repos/")
        requested_path = Path(destination).expanduser()
        if not requested_path.is_absolute():
            raise ValueError("Choose an absolute destination folder")
        target = requested_path.resolve()
        if target.exists():
            raise ValueError("Clone destination must not already exist")
        if not target.parent.is_dir():
            raise ValueError("Clone destination parent folder does not exist")
        self._run("gh", ["repo", "clone", full_name, str(target)])
        if not target.is_dir():
            raise GitHubCLIError("GitHub CLI reported success but the clone folder was not created")
        root, cloned_name = self._local_repository(str(target))
        if cloned_name.casefold() != full_name.casefold():
            raise GitHubCLIError("Cloned repository origin did not match the selected repository")
        return {"project_root": str(root), "repository": cloned_name, "status": "cloned"}

    def _local_repository(self, project_root: str) -> tuple[Path, str]:
        root = Path(project_root).expanduser().resolve()
        if not root.is_dir():
            raise ValueError("Repository folder does not exist")
        top_level = self._git(root, "rev-parse", "--show-toplevel")
        if Path(top_level).resolve() != root:
            raise ValueError("Select the root folder of the Git repository")
        remote = self._git(root, "remote", "get-url", "origin")
        return root, self._github_slug(remote)

    def _repository_permissions(self, owner: str, repository: str) -> dict[str, object]:
        path = self._repository_path(owner, repository)
        payload = self._api("GET", path)
        permissions = payload.get("permissions")
        return permissions if isinstance(permissions, dict) else {}

    def _tracking_status(self, root: Path, branch: str | None) -> dict[str, object]:
        if not branch:
            return {"remote_branch": None, "ahead": None, "behind": None}
        status = self._git(root, "status", "--porcelain=v2", "--branch")
        upstream = next(
            (line.removeprefix("# branch.upstream ") for line in status.splitlines() if line.startswith("# branch.upstream ")),
            None,
        )
        if not upstream:
            return {"remote_branch": None, "ahead": None, "behind": None}
        ahead_behind = next(
            (line for line in status.splitlines() if line.startswith("# branch.ab ")),
            None,
        )
        match = re.fullmatch(r"# branch\.ab \+(\d+) -(\d+)", ahead_behind or "")
        if not match:
            raise GitHubCLIError("Git returned invalid upstream ahead/behind status")
        return {
            "remote_branch": upstream,
            "ahead": int(match.group(1)),
            "behind": int(match.group(2)),
        }

    def _ahead_behind(self, root: Path, remote_ref: str) -> tuple[int, int]:
        counts = self._git(root, "rev-list", "--left-right", "--count", f"HEAD...{remote_ref}").split()
        if len(counts) != 2 or not all(value.isdigit() for value in counts):
            raise GitHubCLIError("Git returned invalid ahead/behind counts")
        return int(counts[0]), int(counts[1])

    def _delete_api(self, endpoint: str) -> None:
        self._run("gh", ["api", "--method", "DELETE", endpoint])

    @staticmethod
    def _github_slug(remote: str) -> str:
        match = re.fullmatch(r"git@github\.com:([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+?)(?:\.git)?", remote)
        if match:
            return f"{match.group(1)}/{match.group(2)}"
        parsed = urlparse(remote)
        if parsed.scheme != "https" or parsed.hostname != "github.com":
            raise ValueError("Repository origin must point to github.com")
        parts = parsed.path.strip("/").removesuffix(".git").split("/")
        if len(parts) != 2:
            raise ValueError("Repository origin must use an owner/repository path")
        return GitHubCLI._repository_path(*parts).removeprefix("repos/")

    @staticmethod
    def _relative_path(path: str) -> str:
        normalized = path.replace("\\", "/")
        parts = normalized.split("/")
        if (
            not normalized
            or normalized.startswith("/")
            or ":" in normalized
            or ".." in parts
            or ".git" in parts
            or any(ord(char) < 32 or ord(char) == 127 for char in normalized)
        ):
            raise ValueError("File paths must stay inside the repository")
        return normalized

    @staticmethod
    def _repository_path(owner: str, repository: str) -> str:
        if not re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9_.-]{0,38})", owner):
            raise ValueError("GitHub owner is invalid")
        if not re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9_.-]{0,99})", repository):
            raise ValueError("GitHub repository name is invalid")
        return f"repos/{owner}/{repository}"

    @staticmethod
    def _validated_owner(owner: str) -> str:
        GitHubCLI._repository_path(owner, "repository")
        return owner

    def _validated_branch(self, branch: str) -> str:
        if not branch or len(branch) > 200 or any(ord(char) < 32 or ord(char) == 127 for char in branch):
            raise ValueError("Branch name is invalid")
        try:
            self._run("git", ["check-ref-format", f"refs/heads/{branch}"])
        except GitHubCLIError as error:
            if error.status_code == 503:
                raise
            raise ValueError("Branch name is invalid") from error
        return branch

    @staticmethod
    def _number(number: int) -> int:
        if number < 1:
            raise ValueError("GitHub item number must be positive")
        return number

    @staticmethod
    def _summary(item: dict[str, object]) -> dict[str, object]:
        return {
            key: item.get(key)
            for key in ("number", "title", "body", "state", "html_url", "user", "created_at", "updated_at", "draft", "merged")
            if key in item
        }

    @staticmethod
    def _repository_summary(item: dict[str, object]) -> dict[str, object]:
        owner = item.get("owner")
        owner_data = owner if isinstance(owner, dict) else {}
        return {
            "name": item.get("name"),
            "full_name": item.get("full_name"),
            "description": item.get("description"),
            "private": bool(item.get("private")),
            "archived": bool(item.get("archived")),
            "visibility": item.get("visibility"),
            "homepage": item.get("homepage"),
            "default_branch": item.get("default_branch"),
            "url": item.get("html_url"),
            "owner": owner_data.get("login"),
            "permissions": item.get("permissions") or {},
        }

    @staticmethod
    def _release_summary(item: dict[str, object]) -> dict[str, object]:
        return {
            key: item.get(key)
            for key in (
                "id", "tag_name", "name", "body", "draft", "prerelease",
                "html_url", "created_at", "published_at",
            )
            if key in item
        }

    def _api_pages(self, endpoint: str, query: dict[str, str]) -> list[object]:
        query_string = urlencode(query)
        response = self._json("gh", ["api", "--paginate", "--slurp", f"{endpoint}?{query_string}"])
        if not isinstance(response, list):
            raise GitHubCLIError("GitHub CLI returned an invalid paginated response")
        pages = []
        for page in response:
            if not isinstance(page, list):
                raise GitHubCLIError("GitHub CLI returned an invalid page")
            pages.extend(page)
        return pages

    def _api(self, method: str, endpoint: str, fields: dict[str, object] | None = None) -> dict[str, object]:
        arguments = ["api", "--method", method, endpoint]
        for name, value in (fields or {}).items():
            flag = "-F" if isinstance(value, bool) else "-f"
            arguments.extend((flag, f"{name}={str(value).lower() if isinstance(value, bool) else value}"))
        response = self._json("gh", arguments)
        if not isinstance(response, dict):
            raise GitHubCLIError("GitHub returned an unexpected response")
        return response

    def _git_names(self, root: Path, *arguments: str) -> list[str]:
        output = self._run("git", ["-C", str(root), *arguments])
        return [item for item in output.split("\0") if item]

    def _git(self, root: Path, *arguments: str) -> str:
        return self._run("git", ["-C", str(root), *arguments]).strip()

    def _json(self, executable: str, arguments: list[str]) -> object:
        output = self._run(executable, arguments)
        try:
            return json.loads(output)
        except json.JSONDecodeError as error:
            raise GitHubCLIError(f"{executable} returned invalid JSON") from error

    def _run(self, executable: str, arguments: list[str]) -> str:
        binary = self._executable_finder(executable)
        if not binary:
            raise GitHubCLIError(f"{executable} is not installed", 503)
        try:
            result = self._runner(
                [binary, *arguments],
                capture_output=True,
                text=True,
                timeout=self._timeout,
                check=False,
            )
        except subprocess.TimeoutExpired as error:
            raise GitHubCLIError(f"{executable} command timed out", 504) from error
        except OSError as error:
            raise GitHubCLIError(f"Unable to start {executable}", 503) from error
        if result.returncode:
            message = result.stderr.strip() or f"{executable} exited with code {result.returncode}"
            match = re.search(r"HTTP\s+(\d{3})", message)
            status_code = int(match.group(1)) if match else 502
            if status_code not in {400, 401, 403, 404, 409, 422, 429}:
                status_code = 502
            message = re.sub(r"\bgh[oprsu]_[A-Za-z0-9_]{20,}\b", "[redacted]", message)
            raise GitHubCLIError(message[:1000], status_code)
        return result.stdout
