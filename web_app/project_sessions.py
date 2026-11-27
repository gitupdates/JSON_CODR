from __future__ import annotations

import errno
import hashlib
import json
import os
import re
import shutil
import stat
import threading
import uuid
from contextlib import contextmanager
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path

from web_app.core.memory import MemoryDraft, MemoryPolicyError, MemoryStore
from web_app.core.project_registry import ProjectRegistry
from web_app.models import ProjectSessionRestoreResult, ProjectSessionSnapshot, SessionRecord
from web_app.workspace import SESSION_ID_PATTERN, WorkspaceService


if os.name == "nt":
    import ctypes
    import msvcrt
    from ctypes import wintypes

    class _ByHandleFileInformation(ctypes.Structure):
        _fields_ = [
            ("dwFileAttributes", wintypes.DWORD),
            ("ftCreationTime", wintypes.FILETIME),
            ("ftLastAccessTime", wintypes.FILETIME),
            ("ftLastWriteTime", wintypes.FILETIME),
            ("dwVolumeSerialNumber", wintypes.DWORD),
            ("nFileSizeHigh", wintypes.DWORD),
            ("nFileSizeLow", wintypes.DWORD),
            ("nNumberOfLinks", wintypes.DWORD),
            ("nFileIndexHigh", wintypes.DWORD),
            ("nFileIndexLow", wintypes.DWORD),
        ]

    _KERNEL32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _CREATE_FILE = _KERNEL32.CreateFileW
    _CREATE_FILE.argtypes = (
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    )
    _CREATE_FILE.restype = wintypes.HANDLE
    _GET_FILE_INFORMATION = _KERNEL32.GetFileInformationByHandle
    _GET_FILE_INFORMATION.argtypes = (
        wintypes.HANDLE,
        ctypes.POINTER(_ByHandleFileInformation),
    )
    _GET_FILE_INFORMATION.restype = wintypes.BOOL
    _CLOSE_HANDLE = _KERNEL32.CloseHandle
    _CLOSE_HANDLE.argtypes = (wintypes.HANDLE,)
    _CLOSE_HANDLE.restype = wintypes.BOOL
    _SET_FILE_INFORMATION = _KERNEL32.SetFileInformationByHandle
    _SET_FILE_INFORMATION.argtypes = (
        wintypes.HANDLE,
        ctypes.c_int,
        wintypes.LPVOID,
        wintypes.DWORD,
    )
    _SET_FILE_INFORMATION.restype = wintypes.BOOL

    class _FileRenameInformation(ctypes.Structure):
        _fields_ = [
            ("Flags", wintypes.DWORD),
            ("RootDirectory", wintypes.HANDLE),
            ("FileNameLength", wintypes.DWORD),
            ("FileName", wintypes.WCHAR * 1),
        ]

    _INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value
    _DELETE = 0x00010000
    _GENERIC_READ = 0x80000000
    _GENERIC_WRITE = 0x40000000
    _FILE_READ_ATTRIBUTES = 0x0080
    _FILE_SHARE_READ = 0x00000001
    _FILE_SHARE_WRITE = 0x00000002
    _CREATE_NEW = 1
    _OPEN_EXISTING = 3
    _FILE_ATTRIBUTE_DIRECTORY = 0x00000010
    _FILE_ATTRIBUTE_NORMAL = 0x00000080
    _FILE_ATTRIBUTE_REPARSE_POINT = 0x00000400
    _FILE_FLAG_OPEN_REPARSE_POINT = 0x00200000
    _FILE_FLAG_BACKUP_SEMANTICS = 0x02000000
    _FILE_FLAG_SEQUENTIAL_SCAN = 0x08000000
    _FILE_RENAME_INFO_CLASS = 3


SNAPSHOT_ID_PATTERN = re.compile(r"^[0-9a-f]{32}$")
_ALLOWED_TREES = ("originals", "extracted", "artifacts")
_HISTORY_FILE = "previous-session-history.md"
_HISTORY_DIGEST_VERSION = 1
_STAGING_PATTERN = re.compile(r"^\.staging-[0-9a-f]{32}$")
_STORAGE_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_EXTRACTED_PATTERN = re.compile(r"^[0-9a-f]{32}\.txt$")


class ProjectSessionService:
    """Creates immutable, project-bound copies of complete live sessions."""

    def __init__(
        self,
        workspace: WorkspaceService,
        projects: ProjectRegistry,
        *,
        memory: MemoryStore | None = None,
        memory_enabled: Callable[[], bool] | None = None,
    ) -> None:
        self.workspace = workspace
        self.projects = projects
        self.root = self.workspace.data_root / "project-sessions"
        self.root.mkdir(parents=True, exist_ok=True)
        self._project_locks_guard = threading.RLock()
        self._project_locks: dict[str, threading.RLock] = {}
        self._windows_transaction_roots = threading.local()
        self.memory = memory
        self.memory_enabled = memory_enabled or (lambda: True)

    @contextmanager
    def _project_lock(self, project_id: str):
        with self._project_locks_guard:
            lock = self._project_locks.setdefault(project_id, threading.RLock())
        with lock:
            yield

    @staticmethod
    def _project_key(project_id: str) -> str:
        return hashlib.sha256(project_id.encode("utf-8")).hexdigest()

    @staticmethod
    def _validate_snapshot_id(snapshot_id: str) -> None:
        if not SNAPSHOT_ID_PATTERN.fullmatch(snapshot_id):
            raise ValueError("Invalid snapshot ID")

    @staticmethod
    def _is_reparse_point(path: Path) -> bool:
        details = path.lstat()
        return path.is_symlink() or bool(
            getattr(details, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT
        )

    def _reject_reparse_tree(self, path: Path) -> None:
        if not path.exists() and not path.is_symlink():
            return
        if self._is_reparse_point(path):
            raise ValueError("Session snapshot source contains a link or reparse point")
        if path.is_dir():
            for child in path.iterdir():
                self._reject_reparse_tree(child)

    def project_directory(self, project_id: str) -> Path:
        self.projects.resolve(project_id)
        directory = self.root / self._project_key(project_id)
        self._check_chain(directory)
        return directory

    def snapshot_directory(self, snapshot_id: str, project_id: str) -> Path:
        self._validate_snapshot_id(snapshot_id)
        directory = self.project_directory(project_id) / "sessions" / snapshot_id
        self._check_chain(directory)
        return directory

    def _check_chain(self, candidate: Path) -> None:
        trusted = self.workspace.data_root.resolve()
        absolute = candidate.absolute()
        if absolute != trusted and trusted not in absolute.parents:
            raise ValueError("Snapshot path escapes the data root")
        current = trusted
        relative = absolute.relative_to(trusted)
        for part in relative.parts:
            current = current / part
            if current.exists() or current.is_symlink():
                if self._is_reparse_point(current):
                    raise ValueError("Snapshot path contains a link or reparse point")

    if os.name == "nt":
        @staticmethod
        def _windows_handle(path: Path, access: int, disposition: int, flags: int):
            handle = _CREATE_FILE(
                str(path),
                access,
                _FILE_SHARE_READ | _FILE_SHARE_WRITE,
                None,
                disposition,
                flags | _FILE_FLAG_OPEN_REPARSE_POINT,
                None,
            )
            if handle == _INVALID_HANDLE_VALUE:
                raise ctypes.WinError(ctypes.get_last_error())
            return handle

        @staticmethod
        def _windows_information(handle):
            information = _ByHandleFileInformation()
            if not _GET_FILE_INFORMATION(handle, ctypes.byref(information)):
                raise ctypes.WinError(ctypes.get_last_error())
            return information

        @staticmethod
        def _windows_close(handle) -> None:
            if handle is not None and handle != _INVALID_HANDLE_VALUE:
                _CLOSE_HANDLE(handle)

        @contextmanager
        def _windows_locked_chain(self, candidate: Path):
            trusted = self.workspace.data_root.absolute()
            absolute = candidate.absolute()
            if absolute != trusted and trusted not in absolute.parents:
                raise ValueError("Snapshot path escapes the data root")
            pinned = None
            for root in getattr(self._windows_transaction_roots, "paths", ()):
                if (absolute == root or root in absolute.parents) and (
                    pinned is None or len(root.parts) > len(pinned.parts)
                ):
                    pinned = root
            paths = [] if pinned is not None else [trusted]
            current = pinned if pinned is not None else trusted
            for part in absolute.relative_to(current).parts:
                current = current / part
                paths.append(current)
            handles = []
            try:
                for path in paths:
                    handle = self._windows_handle(
                        path,
                        _GENERIC_READ | _FILE_READ_ATTRIBUTES,
                        _OPEN_EXISTING,
                        _FILE_FLAG_BACKUP_SEMANTICS,
                    )
                    try:
                        information = self._windows_information(handle)
                    except Exception:
                        self._windows_close(handle)
                        raise
                    if information.dwFileAttributes & _FILE_ATTRIBUTE_REPARSE_POINT:
                        self._windows_close(handle)
                        raise ValueError("Snapshot path contains a link or reparse point")
                    if not information.dwFileAttributes & _FILE_ATTRIBUTE_DIRECTORY:
                        self._windows_close(handle)
                        raise ValueError("Snapshot path ancestor is not a directory")
                    handles.append(handle)
                yield
            finally:
                for handle in reversed(handles):
                    self._windows_close(handle)

        @contextmanager
        def _windows_pinned_transaction_directory(self, path: Path):
            absolute = path.absolute()
            with self._windows_locked_chain(path.parent):
                handle = self._windows_handle(
                    path,
                    _FILE_READ_ATTRIBUTES | _DELETE,
                    _OPEN_EXISTING,
                    _FILE_FLAG_BACKUP_SEMANTICS,
                )
                try:
                    information = self._windows_information(handle)
                    if information.dwFileAttributes & _FILE_ATTRIBUTE_REPARSE_POINT:
                        raise ValueError("Snapshot path contains a link or reparse point")
                    if not information.dwFileAttributes & _FILE_ATTRIBUTE_DIRECTORY:
                        raise ValueError("Snapshot transaction root is not a directory")
                    roots = getattr(self._windows_transaction_roots, "paths", None)
                    if roots is None:
                        roots = []
                        self._windows_transaction_roots.paths = roots
                    roots.append(absolute)
                    try:
                        yield handle
                    finally:
                        roots.pop()
                finally:
                    self._windows_close(handle)

        @staticmethod
        def _windows_promote_directory(handle, destination: Path) -> None:
            encoded = str(destination.absolute()).encode("utf-16-le")
            size = _FileRenameInformation.FileName.offset + len(encoded) + ctypes.sizeof(wintypes.WCHAR)
            buffer = ctypes.create_string_buffer(size)
            information = ctypes.cast(buffer, ctypes.POINTER(_FileRenameInformation))
            information.contents.Flags = 0
            information.contents.RootDirectory = None
            information.contents.FileNameLength = len(encoded)
            ctypes.memmove(
                ctypes.addressof(buffer) + _FileRenameInformation.FileName.offset,
                encoded,
                len(encoded),
            )
            if not _SET_FILE_INFORMATION(
                handle, _FILE_RENAME_INFO_CLASS, buffer, size
            ):
                raise ctypes.WinError(ctypes.get_last_error())

    @contextmanager
    def _locked_copy_directory(self, path: Path):
        if os.name == "nt":
            with self._windows_locked_chain(path):
                yield
            return
        self._check_chain(path)
        flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(path, flags)
        try:
            details = os.fstat(descriptor)
            if not stat.S_ISDIR(details.st_mode):
                raise ValueError("Snapshot path ancestor is not a directory")
            yield
        finally:
            os.close(descriptor)

    @contextmanager
    def _open_copy_source(self, source: Path):
        if os.name == "nt":
            with self._windows_locked_chain(source.parent):
                handle = self._windows_handle(
                    source,
                    _GENERIC_READ | _FILE_READ_ATTRIBUTES,
                    _OPEN_EXISTING,
                    _FILE_FLAG_SEQUENTIAL_SCAN,
                )
                try:
                    information = self._windows_information(handle)
                    if information.dwFileAttributes & (
                        _FILE_ATTRIBUTE_REPARSE_POINT | _FILE_ATTRIBUTE_DIRECTORY
                    ):
                        raise ValueError("Session file is not a non-reparse regular file")
                    descriptor = msvcrt.open_osfhandle(
                        handle, os.O_RDONLY | getattr(os, "O_BINARY", 0)
                    )
                    handle = None
                    with os.fdopen(descriptor, "rb") as reader:
                        yield reader
                finally:
                    self._windows_close(handle)
            return
        self._check_chain(source.parent)
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(source, flags)
        try:
            details = os.fstat(descriptor)
            if not stat.S_ISREG(details.st_mode):
                raise ValueError("Session file is not regular")
            with os.fdopen(descriptor, "rb", closefd=False) as reader:
                yield reader
        finally:
            os.close(descriptor)

    @contextmanager
    def _open_copy_destination(self, destination: Path):
        if os.name == "nt":
            with self._windows_locked_chain(destination.parent):
                handle = self._windows_handle(
                    destination,
                    _GENERIC_WRITE | _FILE_READ_ATTRIBUTES,
                    _CREATE_NEW,
                    _FILE_ATTRIBUTE_NORMAL,
                )
                try:
                    information = self._windows_information(handle)
                    if information.dwFileAttributes & (
                        _FILE_ATTRIBUTE_REPARSE_POINT | _FILE_ATTRIBUTE_DIRECTORY
                    ):
                        raise ValueError("Snapshot destination is not a regular file")
                    descriptor = msvcrt.open_osfhandle(
                        handle, os.O_WRONLY | getattr(os, "O_BINARY", 0)
                    )
                    handle = None
                    with os.fdopen(descriptor, "wb") as writer:
                        yield writer
                finally:
                    self._windows_close(handle)
            return
        self._check_chain(destination.parent)
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(destination, flags, 0o600)
        try:
            details = os.fstat(descriptor)
            if not stat.S_ISREG(details.st_mode):
                raise ValueError("Snapshot destination is not a regular file")
            with os.fdopen(descriptor, "wb", closefd=False) as writer:
                yield writer
        finally:
            os.close(descriptor)

    @contextmanager
    def _create_copy_directory(self, destination: Path):
        with self._locked_copy_directory(destination.parent):
            destination.mkdir()
            with self._locked_copy_directory(destination):
                yield

    @contextmanager
    def _pinned_staging_directory(self, staging: Path):
        if os.name == "nt":
            with self._windows_pinned_transaction_directory(staging) as handle:
                yield handle
            return
        with self._locked_copy_directory(staging):
            yield None

    def _promote_staging(self, staging: Path, final: Path, handle) -> None:
        if os.name == "nt":
            self._windows_promote_directory(handle, final)
            return
        os.replace(staging, final)

    def save(
        self,
        session_id: str,
        project_id: str,
        owner_user_id: str,
        title: str,
        change_type: str,
        keywords: list[str],
    ) -> ProjectSessionSnapshot:
        with self._project_lock(project_id):
            return self._save_locked(session_id, project_id, owner_user_id, title, change_type, keywords)

    def _save_locked(
        self,
        session_id: str,
        project_id: str,
        owner_user_id: str,
        title: str,
        change_type: str,
        keywords: list[str],
    ) -> ProjectSessionSnapshot:
        self.projects.resolve(project_id)
        with self.workspace.session_lock(session_id):
            session = self.workspace.get_session(session_id)
            snapshot_id = uuid.uuid4().hex
            snapshot = ProjectSessionSnapshot(
                id=snapshot_id,
                source_session_id=session.id,
                project_id=project_id,
                owner_user_id=owner_user_id,
                title=title.strip(),
                change_type=change_type.strip(),
                keywords=self._keywords(session, snapshot_id, project_id, title, change_type, keywords),
                summary=self._summary(session, title, change_type),
                created_at=datetime.now(timezone.utc),
            )
            if not snapshot.title or not snapshot.change_type:
                raise ValueError("Snapshot title and change type are required")
            newly_bound = self._bind_live_identity_for_save(session, project_id, owner_user_id)
            try:
                final = self.snapshot_directory(snapshot.id, project_id)
                sessions_root = final.parent
                sessions_root.mkdir(parents=True, exist_ok=True)
                self._check_chain(sessions_root)
                with self._locked_copy_directory(sessions_root):
                    self._sweep_staging(sessions_root)
                    staging = sessions_root / f".staging-{snapshot.id}"
                    indexed_record = None
                    try:
                        staging.mkdir()
                        with self._pinned_staging_directory(staging) as staging_handle:
                            digests = self._copy_live_session(session, staging)
                            history = staging / _HISTORY_FILE
                            history_content = self._history_markdown(snapshot)[:65_536]
                            self._write_text(history, history_content)
                            digests[_HISTORY_FILE] = self._digest(history)
                            snapshot, indexed_record = self._project_history(
                                snapshot, history_content
                            )
                            self._write_json(staging / "snapshot.json", {
                                "snapshot": snapshot.model_dump(mode="json"),
                                "tree_digests": digests,
                                "history_digest_version": _HISTORY_DIGEST_VERSION,
                            })
                            self._validate_snapshot_tree(staging, digests)
                            self._fsync_tree(staging)
                            self._promote_staging(staging, final, staging_handle)
                            self._fsync_directory(final.parent)
                    except Exception:
                        if indexed_record is not None and self.memory is not None:
                            try:
                                self.memory.revoke(
                                    indexed_record.memory_id,
                                    user_id=owner_user_id,
                                    project_id=project_id,
                                    reason="snapshot promotion failed",
                                )
                            except Exception:
                                pass
                        self._remove_tree_no_follow(staging)
                        raise
                return snapshot
            except Exception:
                if newly_bound:
                    session.project_id = None
                    self.workspace.save_manifest(session)
                raise

    def _project_history(self, snapshot: ProjectSessionSnapshot, content: str):
        try:
            enabled = self.memory_enabled()
        except Exception:
            enabled = False
        if self.memory is None or not enabled:
            return snapshot.model_copy(update={
                "indexing_status": "skipped", "indexed_memory_id": None,
            }), None
        draft = MemoryDraft(
            user_id=snapshot.owner_user_id,
            project_id=snapshot.project_id,
            thread_id=snapshot.source_session_id,
            task_id=snapshot.id,
            kind="previous_session_history",
            content=content[:65_536],
            source_refs=(f"previous-session:{snapshot.id}",),
            retain_details=False,
            idempotency_key=f"previous-session:{snapshot.id}",
        )
        try:
            record = self.memory.accept(draft)
        except (MemoryPolicyError, ValueError):
            return snapshot.model_copy(update={
                "indexing_status": "rejected", "indexed_memory_id": None,
            }), None
        except Exception:
            return snapshot.model_copy(update={
                "indexing_status": "skipped", "indexed_memory_id": None,
            }), None
        return snapshot.model_copy(update={
            "indexing_status": "indexed", "indexed_memory_id": record.memory_id,
        }), record

    def list(self, project_id: str, owner_user_id: str, query: str = "") -> list[ProjectSessionSnapshot]:
        directory = self.project_directory(project_id) / "sessions"
        self._check_chain(directory)
        if not directory.exists():
            return []
        records: list[ProjectSessionSnapshot] = []
        needle = query.strip().casefold()
        for candidate in sorted(directory.iterdir(), key=lambda path: path.name):
            if candidate.name.startswith(".") or self._is_reparse_point(candidate) or not candidate.is_dir():
                continue
            try:
                record = self._read_snapshot(candidate)
            except (OSError, ValueError, json.JSONDecodeError):
                continue
            if record.project_id != project_id or record.owner_user_id != owner_user_id:
                continue
            haystack = " ".join([record.title, record.change_type, record.summary, *record.keywords]).casefold()
            if not needle or needle in haystack:
                records.append(record)
        return sorted(records, key=lambda record: (record.created_at, record.id), reverse=True)

    def get(self, snapshot_id: str, project_id: str, owner_user_id: str) -> ProjectSessionSnapshot:
        self.projects.resolve(project_id)
        path = self.snapshot_directory(snapshot_id, project_id)
        if not path.is_dir():
            raise KeyError(snapshot_id)
        record = self._read_snapshot(path)
        if record.project_id != project_id or record.owner_user_id != owner_user_id:
            raise KeyError(snapshot_id)
        return record

    def history(self, snapshot_id: str, project_id: str, owner_user_id: str) -> str:
        """Read verified compact history through the same no-follow snapshot boundary."""
        snapshot = self.get(snapshot_id, project_id, owner_user_id)
        source = self.snapshot_directory(snapshot.id, project_id)
        payload = self._snapshot_payload(source)
        return self._validated_history(snapshot, source, payload)

    def _validated_history(
        self, snapshot: ProjectSessionSnapshot, source: Path, payload: dict[str, object]
    ) -> str:
        digests = payload.get("tree_digests")
        if not isinstance(digests, dict):
            raise ValueError("Snapshot history is incomplete")
        history_version = payload.get("history_digest_version")
        if history_version not in (None, _HISTORY_DIGEST_VERSION):
            raise ValueError("Snapshot history version is invalid")
        legacy = (
            history_version is None
            and snapshot.schema_version == 1
            and _HISTORY_FILE not in digests
        )
        if not legacy and not isinstance(digests.get(_HISTORY_FILE), str):
            raise ValueError("Snapshot history is incomplete")
        self._validate_snapshot_tree(source, digests, exclude_history=legacy)
        try:
            with self._open_copy_source(source / _HISTORY_FILE) as history:
                content = history.read()
            if legacy:
                canonical = self._history_markdown(snapshot).encode("utf-8")
                if content != canonical:
                    raise ValueError("Snapshot history failed canonical validation")
                return canonical.decode("utf-8")
            actual = "sha256:" + hashlib.sha256(content).hexdigest()
            if actual != digests[_HISTORY_FILE]:
                raise ValueError("Snapshot history failed digest validation")
            return content.decode("utf-8")
        except (OSError, UnicodeDecodeError) as error:
            raise ValueError("Snapshot history is incomplete") from error

    def restore(self, snapshot_id: str, project_id: str, owner_user_id: str) -> ProjectSessionRestoreResult:
        snapshot = self.get(snapshot_id, project_id, owner_user_id)
        source = self.snapshot_directory(snapshot.id, project_id)
        payload = self._snapshot_payload(source)
        digests = payload.get("tree_digests")
        if not isinstance(digests, dict):
            raise ValueError("Snapshot digest manifest is invalid")
        self._validated_history(snapshot, source, payload)
        source_manifest = source / "manifest.json"
        restored_manifest = SessionRecord.model_validate(json.loads(self._read_copy_text(source_manifest)))
        self._validate_attachment_sources(restored_manifest, source)
        restored = self.workspace.create_session(owner_user_id, project_id)
        try:
            with self.workspace.session_lock(restored.id):
                target = self.workspace.sessions_root / restored.id
                with self._locked_copy_directory(target):
                    self._copy_snapshot_trees(source, target)
                    self._validate_restored_trees(target, digests)
                    restored_manifest.id = restored.id
                    restored_manifest.created_at = restored.created_at
                    restored_manifest.updated_at = datetime.now(timezone.utc)
                    restored_manifest.owner_user_id = owner_user_id
                    restored_manifest.project_id = project_id
                    restored_manifest.restored_from_snapshot_id = snapshot.id
                    self.workspace.save_manifest(restored_manifest)
            return ProjectSessionRestoreResult(
                session_id=restored.id,
                snapshot_id=snapshot.id,
                project_id=project_id,
                owner_user_id=owner_user_id,
            )
        except Exception:
            self.workspace.delete_session(restored.id)
            raise

    def _require_live_identity(self, session: SessionRecord, project_id: str, owner_user_id: str) -> None:
        if session.project_id != project_id or session.owner_user_id != owner_user_id:
            raise PermissionError("Live session is not available to this owner or project")

    def _bind_live_identity_for_save(
        self, session: SessionRecord, project_id: str, owner_user_id: str
    ) -> bool:
        if not session.owner_user_id or session.owner_user_id != owner_user_id:
            raise PermissionError("Live session is not available to this owner or project")
        if session.project_id is None:
            session.project_id = project_id
            self.workspace.save_manifest(session)
            return True
        self._require_live_identity(session, project_id, owner_user_id)
        return False

    def _copy_live_session(self, session: SessionRecord, destination: Path) -> dict[str, str]:
        source = self.workspace._session_directory(session.id)
        self._reject_reparse_tree(source)
        manifest = source / "manifest.json"
        if not manifest.is_file():
            raise ValueError("Live session manifest is incomplete")
        self._validate_attachment_sources(session, source)
        sanitized = self._sanitized_session(session)
        expected = self._tree_digests(source)
        payload = json.dumps(sanitized.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n"
        expected["manifest.json"] = "sha256:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()
        self._write_json(destination / "manifest.json", sanitized.model_dump(mode="json"))
        self._copy_allowed(source, destination)
        actual = self._tree_digests(destination)
        if actual != expected:
            raise ValueError("Snapshot staging files differ from the locked source")
        self._check_chain(source)
        self._check_chain(destination)
        return expected

    @staticmethod
    def _sanitized_session(session: SessionRecord) -> SessionRecord:
        clean = session.model_copy(deep=True)
        clean.messages = []
        for message in session.messages:
            if message.status in {"pending", "streaming"}:
                continue
            safe = message.model_copy(deep=True)
            safe.task_id = None
            safe.reasoning = (
                safe.reasoning.model_copy(update={"entries": [entry for entry in safe.reasoning.entries if entry.provenance == "public_rationale"]})
                if safe.reasoning else None
            )
            if safe.reasoning is not None and not safe.reasoning.entries:
                safe.reasoning = None
            clean.messages.append(safe)
        return clean

    def _validate_attachment_sources(self, session: SessionRecord, source: Path) -> None:
        for attachment in session.attachments:
            content_bearing = attachment.digest is not None
            if content_bearing and (not attachment.storage_name or not _STORAGE_PATTERN.fullmatch(attachment.storage_name)):
                raise ValueError("Live session attachment storage name is invalid")
            if attachment.storage_name and not _STORAGE_PATTERN.fullmatch(attachment.storage_name):
                raise ValueError("Live session attachment storage name is invalid")
            if attachment.storage_name and attachment.storage_name != attachment.digest:
                raise ValueError("Live session attachment storage does not match its digest")
            if attachment.storage_name and not self._safe_regular(source / "originals", attachment.storage_name):
                raise ValueError("Live session attachment original is missing")
            if attachment.extraction_state.value == "ready" and (
                not attachment.extracted_name or not _EXTRACTED_PATTERN.fullmatch(attachment.extracted_name)
                or not self._safe_regular(source / "extracted", attachment.extracted_name)
            ):
                raise ValueError("Live session attachment extraction is missing")

    def _safe_regular(self, parent: Path, name: str) -> bool:
        if Path(name).name != name or "/" in name or "\\" in name or name in {"", ".", ".."}:
            return False
        self._check_chain(parent)
        path = parent / name
        self._check_chain(path)
        return path.is_file() and not self._is_reparse_point(path)

    def _copy_snapshot_trees(self, source: Path, destination: Path) -> None:
        self._reject_reparse_tree(source)
        for name in _ALLOWED_TREES:
            tree = source / name
            if tree.exists():
                if not tree.is_dir():
                    raise ValueError("Snapshot tree is invalid")
                self._copy_tree_safe(tree, destination / name)

    def _copy_allowed(self, source: Path, destination: Path) -> dict[str, str]:
        for name in _ALLOWED_TREES:
            tree = source / name
            if not tree.exists():
                continue
            if not tree.is_dir() or self._is_reparse_point(tree):
                raise ValueError("Session tree is unsafe")
            self._copy_tree_safe(tree, destination / name)
        return self._tree_digests(destination)

    def _copy_tree_safe(self, source: Path, destination: Path) -> None:
        with self._locked_copy_directory(source):
            if self._is_reparse_point(source) or not source.is_dir():
                raise ValueError("Session tree is unsafe")
            with self._create_copy_directory(destination):
                for child in source.iterdir():
                    if self._is_reparse_point(child):
                        raise ValueError("Session tree contains a link or reparse point")
                    target = destination / child.name
                    if child.is_dir():
                        self._copy_tree_safe(child, target)
                    elif child.is_file():
                        self._copy_file_safe(child, target)
                    else:
                        raise ValueError("Session tree contains an unsafe entry")

    def _copy_file_safe(self, source: Path, destination: Path) -> None:
        with self._open_copy_source(source) as reader, self._open_copy_destination(destination) as writer:
            shutil.copyfileobj(reader, writer)
            writer.flush()
            os.fsync(writer.fileno())

    def _validate_snapshot_tree(
        self, directory: Path, expected: dict[str, object], *, exclude_history: bool = False
    ) -> None:
        self._reject_reparse_tree(directory)
        actual = self._tree_digests(directory)
        wanted = {str(key): str(value) for key, value in expected.items()}
        if exclude_history:
            actual.pop(_HISTORY_FILE, None)
            wanted.pop(_HISTORY_FILE, None)
        if actual != wanted:
            raise ValueError("Snapshot files failed digest validation")

    def _validate_restored_trees(self, directory: Path, expected: dict[str, object]) -> None:
        self._reject_reparse_tree(directory)
        actual = {key: value for key, value in self._tree_digests(directory).items() if key != "manifest.json"}
        wanted = {
            str(key): str(value)
            for key, value in expected.items()
            if str(key) not in {"manifest.json", _HISTORY_FILE}
        }
        if actual != wanted:
            raise ValueError("Restored files failed digest validation")

    def _tree_digests(self, root: Path) -> dict[str, str]:
        output: dict[str, str] = {}
        for relative in [Path("manifest.json"), Path(_HISTORY_FILE), *(Path(name) for name in _ALLOWED_TREES)]:
            candidate = root / relative
            if candidate.is_file():
                output[candidate.relative_to(root).as_posix()] = self._digest(candidate)
            elif candidate.exists():
                if not candidate.is_dir():
                    raise ValueError("Snapshot entry is not a regular file or directory")
                for path in sorted(candidate.rglob("*"), key=lambda item: item.as_posix()):
                    if path.is_dir():
                        continue
                    if not path.is_file() or self._is_reparse_point(path):
                        raise ValueError("Snapshot contains an unsafe file")
                    output[path.relative_to(root).as_posix()] = self._digest(path)
        return output

    def _digest(self, path: Path) -> str:
        digest = hashlib.sha256()
        with self._open_copy_source(path) as source:
            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(chunk)
        return "sha256:" + digest.hexdigest()

    def _read_copy_text(self, path: Path) -> str:
        with self._open_copy_source(path) as source:
            return source.read().decode("utf-8")

    def _read_snapshot(self, directory: Path) -> ProjectSessionSnapshot:
        return ProjectSessionSnapshot.model_validate(self._snapshot_payload(directory)["snapshot"])

    def _snapshot_payload(self, directory: Path) -> dict[str, object]:
        path = directory / "snapshot.json"
        if not path.is_file():
            raise ValueError("Snapshot metadata is missing")
        payload = json.loads(self._read_copy_text(path))
        if not isinstance(payload, dict):
            raise ValueError("Snapshot metadata is invalid")
        return payload

    @staticmethod
    def _write_json(path: Path, payload: object) -> None:
        ProjectSessionService._write_text(path, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")

    @staticmethod
    def _write_text(path: Path, text: str) -> None:
        with path.open("w", encoding="utf-8", newline="\n") as destination:
            destination.write(text)
            destination.flush()
            os.fsync(destination.fileno())

    @staticmethod
    def _fsync_directory(path: Path) -> None:
        try:
            descriptor = os.open(path, os.O_RDONLY)
        except OSError as error:
            if os.name == "nt" and error.errno in {errno.EACCES, errno.EPERM}:
                return
            raise
        try:
            os.fsync(descriptor)
        except OSError as error:
            if not (os.name == "nt" and error.errno in {errno.EBADF, errno.EINVAL}):
                raise
        finally:
            os.close(descriptor)

    def _fsync_tree(self, root: Path) -> None:
        for path in sorted(root.rglob("*"), key=lambda item: item.as_posix()):
            if path.is_file():
                descriptor = os.open(path, os.O_RDONLY)
                try:
                    os.fsync(descriptor)
                except OSError as error:
                    # CPython's Windows CRT rejects fsync on the read-only descriptor
                    # used for an already-written file. Only that exact platform case
                    # is unsupported; every real durability error aborts promotion.
                    if not (os.name == "nt" and error.errno == errno.EBADF):
                        raise
                finally:
                    os.close(descriptor)
            elif path.is_dir():
                self._fsync_directory(path)
        self._fsync_directory(root)

    def _remove_tree_no_follow(self, path: Path) -> None:
        if not path.exists() and not path.is_symlink():
            return
        try:
            if self._is_reparse_point(path):
                try:
                    path.unlink()
                except PermissionError:
                    path.rmdir()
                return
            if path.is_dir():
                for child in path.iterdir():
                    self._remove_tree_no_follow(child)
                path.rmdir()
            else:
                path.unlink()
        except FileNotFoundError:
            return

    def _sweep_staging(self, sessions_root: Path) -> None:
        for candidate in sessions_root.iterdir():
            if not _STAGING_PATTERN.fullmatch(candidate.name):
                continue
            if self._is_reparse_point(candidate) or not candidate.is_dir():
                raise ValueError("Snapshot staging entry is unsafe")
            self._reject_reparse_tree(candidate)
            shutil.rmtree(candidate)

    @staticmethod
    def _slug(value: str) -> str:
        return re.sub(r"[^a-z0-9._/-]+", "-", value.casefold()).strip("-./")[:120]

    def _keywords(
        self,
        session: SessionRecord,
        snapshot_id: str,
        project_id: str,
        title: str,
        change_type: str,
        supplied: list[str],
    ) -> list[str]:
        required = {
            f"snapshot:{snapshot_id}", f"project:{project_id}", f"session:{session.id}", f"change-type:{self._slug(change_type)}",
            f"title:{self._slug(title)}",
        }
        values = set(required)
        for value in supplied:
            raw = str(value).strip()
            namespace, separator, detail = raw.partition(":")
            normalized = (f"{namespace.casefold()}:{self._slug(detail)}" if separator and namespace.casefold() in {"component", "file", "model", "task", "reference"} else self._slug(raw))
            if normalized:
                values.add(normalized)
        for attachment in session.attachments:
            name = self._slug(attachment.display_name)
            if name:
                values.add(f"file:{name}")
        for message in session.messages:
            for model in (message.requested_model, message.effective_model):
                if model and self._slug(model):
                    values.add(f"model:{self._slug(model)}")
            if message.task_id and self._slug(message.task_id):
                values.add(f"task:{self._slug(message.task_id)}")
            for reference in message.references:
                if self._slug(reference.id):
                    values.add(f"reference:{self._slug(reference.id)}")
                if reference.kind == "project_file" and self._slug(reference.label):
                    values.add(f"file:{self._slug(reference.label)}")
                    parts = self._slug(reference.label).split("/")
                    if len(parts) > 1:
                        values.add(f"component:{parts[-2]}")
        optional = sorted(values - required)
        return sorted(required) + optional[:max(0, 128 - len(required))]

    def _summary(self, session: SessionRecord, title: str, change_type: str) -> str:
        metadata = [f"Title: {title.strip()}", f"Change type: {change_type.strip()}", f"Created: {session.created_at.isoformat()}"]
        objectives: list[str] = []
        outcomes: list[str] = []
        models: list[str] = []
        references: list[str] = []
        attachments: list[str] = []
        warnings: list[str] = []
        for message in session.messages:
            if message.role == "user":
                objectives.append(f"Objective: {message.content[:400]}")
            elif message.role == "assistant":
                outcomes.append(f"Outcome ({message.status}): {message.content[:500]}")
            if message.effective_model or message.requested_model:
                models.append(f"Model: {message.effective_model or message.requested_model}")
            if message.task_id:
                models.append(f"Task: {message.task_id}")
            for reference in message.references:
                references.append(f"Reference: {reference.label[:300]}")
        for attachment in session.attachments:
            attachments.append(f"Attachment: {attachment.display_name[:300]}")
            for warning in attachment.warnings:
                warnings.append(f"Warning: {warning[:300]}")
        def within(lines: list[str], budget: int) -> list[str]:
            used = 0
            output: list[str] = []
            for line in lines:
                available = budget - used
                if available <= 1:
                    break
                item = line[:available - 1]
                output.append(item)
                used += len(item) + 1
            return output

        groups = (
            within(metadata, 800), within(objectives[:6], 1_500), within(outcomes[:6], 1_800),
            within(models[:12], 900), within(references[:12], 900), within(attachments[:12], 900),
            within(warnings[:12], 900),
        )
        return "\n".join(line for group in groups for line in group)[:8_000]

    @staticmethod
    def _history_markdown(snapshot: ProjectSessionSnapshot) -> str:
        keywords = ", ".join(snapshot.keywords)
        return f"---\nsnapshot: {snapshot.id}\nkeywords: [{keywords}]\n---\n\n{snapshot.summary}\n"
