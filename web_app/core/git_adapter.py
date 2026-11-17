from __future__ import annotations

from pathlib import Path

from web_app.core.contracts import FrozenContract, TaskId


class WorktreeRecord(FrozenContract):
    task_id: TaskId
    repository_root: str
    worktree_root: str
    branch: str
    base_commit: str


class MergeEvidence(FrozenContract):
    task_id: TaskId
    branch: str
    commit: str
    output: str


class GitAdapter:
    def __init__(self, broker) -> None:
        self._broker = broker

    def create_worktree(
        self, repository_root: str | Path, worktree_root: str | Path, branch: str, task_id: str
    ) -> WorktreeRecord:
        values = self._broker.create_worktree(repository_root, worktree_root, branch)
        return WorktreeRecord(
            task_id=task_id,
            **values,
        )

    def merge_worktree(self, repository_root: str | Path, record: WorktreeRecord) -> MergeEvidence:
        values = self._broker.merge_worktree_branch(repository_root, record.branch)
        return MergeEvidence(task_id=record.task_id, **values)
