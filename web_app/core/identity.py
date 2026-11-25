from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
import hashlib
import hmac
import json
import secrets
import sqlite3
from typing import Literal
from uuid import uuid4

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

from web_app.designer.access import _ROLE_GRANTS
from web_app.designer.access import CapabilityProfile, DesignPolicyContext, ProfileAssignment
from web_app.core.auth import (
    CredentialKind,
    DevelopmentBypassSettings,
    IssuedCredential,
    LocalRequestEvidence,
    load_or_create_protected_key,
)


IdentityRoleName = Literal[
    "owner",
    "administrator",
    "designer",
    "editor",
    "contributor",
    "reviewer",
    "viewer",
]
IdentityMode = Literal["development", "production"]


MUTATION_SCOPES = (
    "git.read",
    "git.edit",
    "git.commit",
    "git.push",
    "agent.launch",
    "terminal.write",
    "session.write",
    "component.install",
    "system.update",
    "system.activate",
    "system.rollback",
    "verification.profiles.manage",
)

VERIFIER_SERVICE_USERNAME = "json-codr-verifier"
VERIFIER_SERVICE_PURPOSE = "lesson_verifier"
VERIFIER_SERVICE_SCOPES = ("lesson.verify", "lesson.verification.record")


@dataclass(frozen=True)
class PasswordPolicy:
    memory_cost_kib: int = 65_536
    time_cost: int = 3
    parallelism: int = 1


@dataclass(frozen=True)
class IdentityRole:
    name: str
    grants: tuple[str, ...]


@dataclass(frozen=True)
class IdentityUser:
    user_id: str
    username: str
    normalized_username: str
    display_name: str
    status: str
    require_password_change: bool
    roles: tuple[str, ...]


@dataclass(frozen=True)
class AuthenticatedPrincipal:
    user_id: str
    username: str
    roles: tuple[str, ...]
    groups: tuple[str, ...] = ()
    profiles: tuple[str, ...] = ()
    credential_id: str | None = None
    credential_kind: str | None = None
    scopes: tuple[str, ...] = ()
    authentication_source: str = "password"


@dataclass(frozen=True)
class BootstrapState:
    completed: bool
    mode: IdentityMode | None
    administrator_user_id: str | None
    credentials_permanent: bool = False


@dataclass(frozen=True)
class TemporaryCredential:
    secret: str = field(repr=False)
    expires_at: datetime
    expires_in_seconds: int = 1_800
    single_use: bool = True


@dataclass(frozen=True)
class BootstrapResult:
    created: bool
    user: IdentityUser
    temporary_credential: TemporaryCredential | None = None


class _ClosingConnection(sqlite3.Connection):
    def __exit__(self, exc_type, exc_value, traceback) -> bool:
        try:
            return super().__exit__(exc_type, exc_value, traceback)
        finally:
            self.close()


class IdentityService:
    def __init__(
        self,
        data_root: Path,
        *,
        now=lambda: datetime.now(UTC),
        security_root: Path | None = None,
    ):
        self.data_root = Path(data_root)
        self.database_path = self.data_root / "core" / "identity.sqlite"
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._now = now
        self.password_policy = PasswordPolicy()
        self._hasher = PasswordHasher(
            memory_cost=self.password_policy.memory_cost_kib,
            time_cost=self.password_policy.time_cost,
            parallelism=self.password_policy.parallelism,
        )
        self._initialize()
        self._dummy_hash = self._hasher.hash(secrets.token_urlsafe(24))
        security_root = security_root or self.data_root.parent / f".{self.data_root.name}-identity"
        self.protected_key_path = Path(security_root) / "identity.key.dpapi"
        self.audit_anchor_path = Path(security_root) / "identity.audit.anchor"
        self._hmac_key_cache: bytes | None = None

    @property
    def _hmac_key(self) -> bytes:
        if self._hmac_key_cache is None:
            self._hmac_key_cache = load_or_create_protected_key(self.protected_key_path)
        return self._hmac_key_cache

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path, factory=_ClosingConnection)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def _initialize(self) -> None:
        schema = """
        CREATE TABLE IF NOT EXISTS identity_users (
            user_id TEXT PRIMARY KEY,
            username TEXT NOT NULL,
            normalized_username TEXT NOT NULL UNIQUE,
            display_name TEXT NOT NULL,
            status TEXT NOT NULL CHECK(status IN ('active', 'disabled')),
            password_hash TEXT,
            password_expires_at TEXT,
            require_password_change INTEGER NOT NULL DEFAULT 0,
            bootstrap_account INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TRIGGER IF NOT EXISTS identity_users_immutable_id
        BEFORE UPDATE OF user_id ON identity_users
        BEGIN SELECT RAISE(ABORT, 'identity user id is immutable'); END;
        CREATE TABLE IF NOT EXISTS identity_roles (
            role_name TEXT PRIMARY KEY,
            grants_json TEXT NOT NULL,
            builtin INTEGER NOT NULL DEFAULT 1
        );
        CREATE TABLE IF NOT EXISTS identity_user_roles (
            user_id TEXT NOT NULL REFERENCES identity_users(user_id) ON DELETE CASCADE,
            role_name TEXT NOT NULL REFERENCES identity_roles(role_name),
            assigned_at TEXT NOT NULL,
            PRIMARY KEY(user_id, role_name)
        );
        CREATE TABLE IF NOT EXISTS identity_groups (
            group_id TEXT PRIMARY KEY, name TEXT NOT NULL UNIQUE, created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS identity_group_members (
            group_id TEXT NOT NULL REFERENCES identity_groups(group_id) ON DELETE CASCADE,
            user_id TEXT NOT NULL REFERENCES identity_users(user_id) ON DELETE CASCADE,
            PRIMARY KEY(group_id, user_id)
        );
        CREATE TABLE IF NOT EXISTS identity_group_roles (
            group_id TEXT NOT NULL REFERENCES identity_groups(group_id) ON DELETE CASCADE,
            role_name TEXT NOT NULL REFERENCES identity_roles(role_name),
            PRIMARY KEY(group_id, role_name)
        );
        CREATE TABLE IF NOT EXISTS identity_profiles (
            profile_id TEXT PRIMARY KEY, label TEXT NOT NULL, grants_json TEXT NOT NULL, denies_json TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS identity_profile_assignments (
            assignment_id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL REFERENCES identity_users(user_id) ON DELETE CASCADE,
            profile_id TEXT NOT NULL REFERENCES identity_profiles(profile_id) ON DELETE CASCADE,
            resource TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS identity_sessions (
            credential_id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL REFERENCES identity_users(user_id) ON DELETE CASCADE,
            kind TEXT NOT NULL CHECK(kind IN ('browser_session', 'cli', 'service')),
            label TEXT NOT NULL,
            credential_purpose TEXT,
            token_hash TEXT NOT NULL UNIQUE,
            scopes_json TEXT NOT NULL,
            issued_at TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            idle_expires_at TEXT,
            last_used_at TEXT,
            revoked_at TEXT
        );
        CREATE TABLE IF NOT EXISTS identity_audit (
            audit_id TEXT PRIMARY KEY, actor_id TEXT, target_id TEXT, operation TEXT NOT NULL,
            changed_fields_json TEXT NOT NULL, reason TEXT NOT NULL, correlation_id TEXT,
            previous_hash TEXT, entry_hash TEXT, created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS identity_external_links (
            provider TEXT NOT NULL, external_subject_id TEXT NOT NULL,
            user_id TEXT NOT NULL REFERENCES identity_users(user_id) ON DELETE CASCADE,
            created_at TEXT NOT NULL, PRIMARY KEY(provider, external_subject_id)
        );
        CREATE TABLE IF NOT EXISTS identity_bootstrap_state (
            singleton INTEGER PRIMARY KEY CHECK(singleton = 1), completed INTEGER NOT NULL,
            mode TEXT, administrator_user_id TEXT, development_expires_at TEXT,
            development_do_not_expire INTEGER NOT NULL DEFAULT 0,
            development_credentials_permanent INTEGER NOT NULL DEFAULT 0,
            updated_at TEXT NOT NULL
        );
        """
        with self._connect() as connection:
            connection.executescript(schema)
            columns = {row[1] for row in connection.execute("PRAGMA table_info(identity_sessions)")}
            if "credential_purpose" not in columns:
                connection.execute("ALTER TABLE identity_sessions ADD COLUMN credential_purpose TEXT")
            state_columns = {row[1] for row in connection.execute("PRAGMA table_info(identity_bootstrap_state)")}
            if "development_credentials_permanent" not in state_columns:
                connection.execute(
                    "ALTER TABLE identity_bootstrap_state ADD COLUMN development_credentials_permanent INTEGER NOT NULL DEFAULT 0"
                )
            for name, grants in _ROLE_GRANTS.items():
                connection.execute(
                    "INSERT OR IGNORE INTO identity_roles(role_name, grants_json) VALUES (?, ?)",
                    (name, json.dumps(sorted(grants))),
                )
            connection.execute(
                "INSERT OR IGNORE INTO identity_bootstrap_state(singleton, completed, updated_at) VALUES (1, 0, ?)",
                (self._iso(self._now()),),
            )
            connection.execute(
                """UPDATE identity_bootstrap_state SET development_credentials_permanent=1
                    WHERE mode='non-production'"""
            )
            connection.execute(
                """UPDATE identity_bootstrap_state SET mode='development'
                    WHERE mode IN ('non-production', 'migration')"""
            )

    @staticmethod
    def _iso(value: datetime) -> str:
        return value.astimezone(UTC).isoformat()

    @staticmethod
    def _normalize(username: str) -> str:
        normalized = username.strip().casefold()
        if not normalized:
            raise ValueError("username is required")
        return normalized

    def bootstrap(self, mode: str, administrator_name: str = "Administrator") -> BootstrapResult:
        if mode not in {"production", "development"}:
            raise ValueError("bootstrap mode must be production or development")
        existing = self._user_by_normalized(self._normalize(administrator_name))
        if existing:
            return BootstrapResult(created=False, user=existing)
        now = self._now()
        temporary = None
        if mode == "production":
            secret = secrets.token_urlsafe(32)
            password_hash = self._hasher.hash(secret)
            expires_at = now + timedelta(minutes=30)
            require_change = True
            temporary = TemporaryCredential(secret=secret, expires_at=expires_at)
        else:
            password_hash = self._hasher.hash("")
            expires_at = None
            require_change = False
        user = self.create_user(
            administrator_name,
            administrator_name,
            password_hash=password_hash,
            password_expires_at=expires_at,
            require_password_change=require_change,
            roles=("administrator",),
            bootstrap_account=True,
        )
        with self._connect() as connection:
            connection.execute(
                "UPDATE identity_bootstrap_state SET completed=1, mode=?, administrator_user_id=?, updated_at=? WHERE singleton=1",
                (mode, user.user_id, self._iso(now)),
            )
        return BootstrapResult(created=True, user=user, temporary_credential=temporary)

    def bootstrap_nonproduction_administrator(
        self, password: str, administrator_name: str = "Administrator",
    ) -> BootstrapResult:
        """Create the one permanent local bootstrap administrator.

        This deliberately lives on the identity service rather than in an
        installer so callers never edit the identity database directly.
        """
        if not password:
            raise ValueError("Administrator password must not be blank")
        state = self.bootstrap_state()
        existing = self._user_by_normalized(self._normalize(administrator_name))
        if state.completed or existing:
            if existing and state.mode == "development":
                return BootstrapResult(created=False, user=existing)
            raise RuntimeError("an existing identity installation must be reconciled manually")
        user = self.create_user(
            administrator_name,
            administrator_name,
            password_hash=self._hasher.hash(password),
            password_expires_at=None,
            require_password_change=False,
            roles=("administrator",),
            bootstrap_account=True,
        )
        with self._connect() as connection:
            connection.execute(
                """UPDATE identity_bootstrap_state SET completed=1, mode='development',
                    administrator_user_id=?, development_credentials_permanent=1,
                    updated_at=? WHERE singleton=1""",
                (user.user_id, self._iso(self._now())),
            )
        self._audit(
            "identity.nonproduction_bootstrap",
            actor_id=user.user_id,
            target_id=user.user_id,
            reason="permanent local administrator initialized",
            changed_fields={"credential_policy": "non-expiring-revocable"},
        )
        return BootstrapResult(created=True, user=user)

    def activate_production(self) -> TemporaryCredential:
        """Atomically leave development mode and invalidate every development credential."""
        now = self._now()
        secret = secrets.token_urlsafe(32)
        expires_at = now + timedelta(minutes=30)
        password_hash = self._hasher.hash(secret)
        revoked = 0
        administrator_user_id: str | None = None
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            state = connection.execute(
                "SELECT mode, administrator_user_id FROM identity_bootstrap_state WHERE singleton=1"
            ).fetchone()
            if not state or state["mode"] != "development" or not state["administrator_user_id"]:
                raise RuntimeError("production activation requires a completed development identity")
            administrator_user_id = str(state["administrator_user_id"])
            timestamp = self._iso(now)
            revoked = connection.execute(
                "UPDATE identity_sessions SET revoked_at=? WHERE revoked_at IS NULL",
                (timestamp,),
            ).rowcount
            connection.execute(
                """UPDATE identity_users SET password_hash=?, password_expires_at=?,
                    require_password_change=1, updated_at=? WHERE user_id=?""",
                (password_hash, self._iso(expires_at), timestamp, administrator_user_id),
            )
            connection.execute(
                """UPDATE identity_bootstrap_state SET mode='production',
                    development_expires_at=NULL, development_do_not_expire=0,
                    development_credentials_permanent=0,
                    updated_at=? WHERE singleton=1""",
                (timestamp,),
            )
        self._audit(
            "identity.production_activated",
            actor_id=administrator_user_id,
            target_id=administrator_user_id,
            reason="development identity retired for production activation",
            changed_fields={"revoked_credentials": revoked, "password_reset_required": True},
        )
        return TemporaryCredential(secret=secret, expires_at=expires_at)

    def bootstrap_state(self) -> BootstrapState:
        with self._connect() as connection:
            row = connection.execute(
                """SELECT completed, mode, administrator_user_id,
                    development_credentials_permanent
                    FROM identity_bootstrap_state WHERE singleton=1"""
            ).fetchone()
        return BootstrapState(
            completed=bool(row["completed"]),
            mode=row["mode"],
            administrator_user_id=row["administrator_user_id"],
            credentials_permanent=bool(row["development_credentials_permanent"]),
        )

    def bootstrap_migrated(self, administrator_name: str = "Administrator") -> BootstrapResult:
        existing = self._user_by_normalized(self._normalize(administrator_name))
        if existing:
            return BootstrapResult(created=False, user=existing)
        user = self.create_user(
            administrator_name,
            administrator_name,
            password_hash=None,
            require_password_change=True,
            roles=("administrator",),
            bootstrap_account=True,
        )
        with self._connect() as connection:
            connection.execute(
                """UPDATE identity_bootstrap_state SET completed=1, mode='development',
                    administrator_user_id=?, development_expires_at=NULL,
                    development_do_not_expire=0, updated_at=? WHERE singleton=1""",
                (user.user_id, self._iso(self._now())),
            )
        return BootstrapResult(created=True, user=user)

    def development_bypass(self) -> DevelopmentBypassSettings:
        with self._connect() as connection:
            row = connection.execute(
                """SELECT mode, development_expires_at, development_do_not_expire
                    FROM identity_bootstrap_state WHERE singleton=1"""
            ).fetchone()
        if row["mode"] != "development":
            return DevelopmentBypassSettings()
        do_not_expire = bool(row["development_do_not_expire"])
        expires_at = datetime.fromisoformat(row["development_expires_at"]) if row["development_expires_at"] else None
        enabled = do_not_expire or bool(expires_at and expires_at > self._now())
        return DevelopmentBypassSettings(
            enabled=enabled,
            do_not_expire=do_not_expire if enabled else False,
            expires_at=None if do_not_expire else expires_at if enabled else None,
        )

    def confirm_development_bypass(
        self,
        evidence: LocalRequestEvidence,
        *,
        configured_host: str,
        do_not_expire: bool = False,
    ) -> DevelopmentBypassSettings:
        evidence.require_direct_loopback(configured_host)
        with self._connect() as connection:
            state = connection.execute(
                "SELECT mode, administrator_user_id FROM identity_bootstrap_state WHERE singleton=1"
            ).fetchone()
            if not state or not state["administrator_user_id"]:
                raise RuntimeError("identity bootstrap is incomplete")
            if state["mode"] != "development":
                raise PermissionError("development bypass is unavailable in production mode")
            expires_at = None if do_not_expire else self._now() + timedelta(days=30)
            connection.execute(
                """UPDATE identity_users SET password_hash=?, password_expires_at=NULL,
                    require_password_change=0, updated_at=? WHERE user_id=?""",
                (self._hasher.hash(""), self._iso(self._now()), state["administrator_user_id"]),
            )
            connection.execute(
                """UPDATE identity_bootstrap_state SET development_expires_at=?,
                    development_do_not_expire=?, updated_at=? WHERE singleton=1""",
                (self._iso(expires_at) if expires_at else None, int(do_not_expire), self._iso(self._now())),
            )
        self._audit(
            "development_bypass.confirmed",
            actor_id=state["administrator_user_id"],
            target_id=state["administrator_user_id"],
            reason="direct local operator confirmation",
            changed_fields={"do_not_expire": do_not_expire, "expires_at": self._iso(expires_at) if expires_at else None},
        )
        return self.development_bypass()

    def renew_development_bypass(
        self,
        evidence: LocalRequestEvidence,
        *,
        configured_host: str,
        do_not_expire: bool = False,
    ) -> DevelopmentBypassSettings:
        if not self.development_bypass().enabled:
            raise PermissionError("development bypass must be confirmed before renewal")
        return self.confirm_development_bypass(
            evidence, configured_host=configured_host, do_not_expire=do_not_expire
        )

    def begin_local_recovery(
        self,
        evidence: LocalRequestEvidence,
        *,
        configured_host: str,
    ) -> TemporaryCredential:
        evidence.require_direct_loopback(configured_host)
        if self.development_bypass().enabled:
            raise PermissionError("recovery is unavailable while development bypass is active")
        with self._connect() as connection:
            state = connection.execute(
                "SELECT administrator_user_id FROM identity_bootstrap_state WHERE singleton=1"
            ).fetchone()
            if not state or not state["administrator_user_id"]:
                raise RuntimeError("identity bootstrap is incomplete")
            secret = secrets.token_urlsafe(32)
            expires_at = self._now() + timedelta(minutes=30)
            connection.execute(
                """UPDATE identity_users SET password_hash=?, password_expires_at=?,
                    require_password_change=1, updated_at=? WHERE user_id=?""",
                (self._hasher.hash(secret), self._iso(expires_at), self._iso(self._now()), state["administrator_user_id"]),
            )
        self._audit(
            "identity.recovery_issued",
            actor_id=state["administrator_user_id"],
            target_id=state["administrator_user_id"],
            reason="direct local recovery",
        )
        return TemporaryCredential(secret=secret, expires_at=expires_at)

    def create_user(
        self,
        username: str,
        display_name: str,
        *,
        password_hash: str | None = None,
        password_expires_at: datetime | None = None,
        require_password_change: bool = False,
        roles: tuple[str, ...] = ("viewer",),
        bootstrap_account: bool = False,
    ) -> IdentityUser:
        normalized = self._normalize(username)
        now = self._iso(self._now())
        user_id = str(uuid4())
        try:
            with self._connect() as connection:
                connection.execute(
                    """INSERT INTO identity_users(
                        user_id, username, normalized_username, display_name, status, password_hash,
                        password_expires_at, require_password_change, bootstrap_account, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, 'active', ?, ?, ?, ?, ?, ?)""",
                    (
                        user_id,
                        username.strip(),
                        normalized,
                        display_name.strip() or username.strip(),
                        password_hash,
                        self._iso(password_expires_at) if password_expires_at else None,
                        int(require_password_change),
                        int(bootstrap_account),
                        now,
                        now,
                    ),
                )
                self._replace_roles(connection, user_id, roles, now)
        except sqlite3.IntegrityError as error:
            if "normalized_username" in str(error):
                raise ValueError("username already exists") from error
            raise
        return self.get_user(user_id)

    def _replace_roles(self, connection: sqlite3.Connection, user_id: str, roles: tuple[str, ...], now: str) -> None:
        if not roles:
            raise ValueError("at least one role is required")
        known = {row[0] for row in connection.execute("SELECT role_name FROM identity_roles")}
        if any(role not in known for role in roles):
            raise ValueError("unknown role")
        connection.execute("DELETE FROM identity_user_roles WHERE user_id = ?", (user_id,))
        connection.executemany(
            "INSERT INTO identity_user_roles(user_id, role_name, assigned_at) VALUES (?, ?, ?)",
            ((user_id, role, now) for role in dict.fromkeys(roles)),
        )

    def _user_by_normalized(self, normalized: str) -> IdentityUser | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT user_id FROM identity_users WHERE normalized_username = ?", (normalized,)
            ).fetchone()
        return self.get_user(row[0]) if row else None

    def get_user(self, user_id: str) -> IdentityUser:
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM identity_users WHERE user_id = ?", (user_id,)).fetchone()
            if not row:
                raise KeyError(user_id)
            roles = tuple(
                item[0]
                for item in connection.execute(
                    "SELECT role_name FROM identity_user_roles WHERE user_id = ? ORDER BY role_name", (user_id,)
                )
            )
        return IdentityUser(
            user_id=row["user_id"],
            username=row["username"],
            normalized_username=row["normalized_username"],
            display_name=row["display_name"],
            status=row["status"],
            require_password_change=bool(row["require_password_change"]),
            roles=roles,
        )

    def list_users(self) -> tuple[IdentityUser, ...]:
        with self._connect() as connection:
            ids = [row[0] for row in connection.execute("SELECT user_id FROM identity_users ORDER BY normalized_username")]
        return tuple(self.get_user(user_id) for user_id in ids)

    def list_roles(self) -> tuple[IdentityRole, ...]:
        with self._connect() as connection:
            rows = connection.execute("SELECT role_name, grants_json FROM identity_roles ORDER BY role_name").fetchall()
        return tuple(IdentityRole(name=row[0], grants=tuple(json.loads(row[1]))) for row in rows)

    def authenticate_password(self, username: str, password: str) -> bool:
        normalized = self._normalize(username)
        with self._connect() as connection:
            row = connection.execute(
                "SELECT password_hash, password_expires_at, status FROM identity_users WHERE normalized_username = ?",
                (normalized,),
            ).fetchone()
        candidate_hash = row["password_hash"] if row and row["password_hash"] else self._dummy_hash
        try:
            verified = self._hasher.verify(candidate_hash, password)
        except (VerificationError, InvalidHashError):
            verified = False
        if not row or row["status"] != "active":
            return False
        if password == "" and not self.development_bypass().enabled:
            return False
        if row["password_expires_at"] and datetime.fromisoformat(row["password_expires_at"]) <= self._now():
            return False
        return bool(verified)

    def change_password(self, username: str, current_password: str, new_password: str) -> None:
        if not new_password:
            raise ValueError("new password must not be blank")
        if not self.authenticate_password(username, current_password):
            raise PermissionError("invalid credentials")
        self.reset_password(username, new_password, require_password_change=False)

    def reset_password(self, username: str, new_password: str, *, require_password_change: bool = True) -> None:
        if not new_password:
            raise ValueError("new password must not be blank")
        normalized = self._normalize(username)
        with self._connect() as connection:
            updated = connection.execute(
                """UPDATE identity_users SET password_hash=?, password_expires_at=NULL,
                    require_password_change=?, updated_at=? WHERE normalized_username=?""",
                (self._hasher.hash(new_password), int(require_password_change), self._iso(self._now()), normalized),
            ).rowcount
        if not updated:
            raise KeyError(username)
        user = self._user_by_normalized(normalized)
        self.revoke_user_credentials(user.user_id, actor_id=user.user_id, reason="password changed")

    def _recovery_count(self, *, excluding: str | None = None) -> int:
        query = """SELECT COUNT(DISTINCT u.user_id) FROM identity_users u
            JOIN identity_user_roles r ON r.user_id=u.user_id
            WHERE u.status='active' AND r.role_name IN ('owner','administrator')"""
        parameters: tuple[str, ...] = ()
        if excluding:
            query += " AND u.user_id != ?"
            parameters = (excluding,)
        with self._connect() as connection:
            return int(connection.execute(query, parameters).fetchone()[0])

    def disable_user(self, user_id: str) -> None:
        user = self.get_user(user_id)
        if set(user.roles) & {"owner", "administrator"} and self._recovery_count(excluding=user_id) == 0:
            raise PermissionError("last recovery-capable account cannot be disabled")
        with self._connect() as connection:
            connection.execute(
                "UPDATE identity_users SET status='disabled', updated_at=? WHERE user_id=?",
                (self._iso(self._now()), user_id),
            )

    def assign_roles(self, user_id: str, roles: tuple[str, ...]) -> IdentityUser:
        current = self.get_user(user_id)
        if set(current.roles) & {"owner", "administrator"} and not set(roles) & {"owner", "administrator"}:
            if self._recovery_count(excluding=user_id) == 0:
                raise PermissionError("last recovery-capable account cannot be demoted")
        with self._connect() as connection:
            self._replace_roles(connection, user_id, roles, self._iso(self._now()))
        return self.get_user(user_id)

    def create_profile(
        self,
        profile_id: str,
        label: str,
        grants: tuple[str, ...],
        denies: tuple[str, ...],
    ) -> CapabilityProfile:
        profile = CapabilityProfile(profile_id=profile_id, label=label, grants=grants, denies=denies)
        with self._connect() as connection:
            connection.execute(
                """INSERT INTO identity_profiles(profile_id, label, grants_json, denies_json)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(profile_id) DO UPDATE SET label=excluded.label,
                    grants_json=excluded.grants_json, denies_json=excluded.denies_json""",
                (profile.profile_id, profile.label, json.dumps(profile.grants), json.dumps(profile.denies)),
            )
        return profile

    def assign_profile(self, user_id: str, profile_id: str, resource: str) -> ProfileAssignment:
        self.get_user(user_id)
        assignment = ProfileAssignment(
            assignment_id=str(uuid4()), subject_id=user_id, profile_id=profile_id, resource=resource
        )
        with self._connect() as connection:
            if not connection.execute(
                "SELECT 1 FROM identity_profiles WHERE profile_id=?", (profile_id,)
            ).fetchone():
                raise KeyError(profile_id)
            connection.execute(
                """INSERT INTO identity_profile_assignments(assignment_id, user_id, profile_id, resource)
                    VALUES (?, ?, ?, ?)""",
                (assignment.assignment_id, user_id, profile_id, resource),
            )
        return assignment

    def create_group(self, name: str, roles: tuple[str, ...] = ()) -> str:
        group_id = str(uuid4())
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO identity_groups(group_id, name, created_at) VALUES (?, ?, ?)",
                (group_id, name.strip(), self._iso(self._now())),
            )
            for role in roles:
                connection.execute(
                    "INSERT INTO identity_group_roles(group_id, role_name) VALUES (?, ?)", (group_id, role)
                )
        return group_id

    def add_group_member(self, group_id: str, user_id: str) -> None:
        self.get_user(user_id)
        with self._connect() as connection:
            connection.execute(
                "INSERT OR IGNORE INTO identity_group_members(group_id, user_id) VALUES (?, ?)",
                (group_id, user_id),
            )

    def design_policy_context(
        self,
        principal: AuthenticatedPrincipal,
        resource: str,
    ) -> DesignPolicyContext:
        user = self.get_user(principal.user_id)
        precedence = ("owner", "administrator", "designer", "editor", "contributor", "reviewer", "viewer")
        with self._connect() as connection:
            group_roles = {
                row[0]
                for row in connection.execute(
                    """SELECT gr.role_name FROM identity_group_members gm
                        JOIN identity_group_roles gr ON gr.group_id=gm.group_id WHERE gm.user_id=?""",
                    (user.user_id,),
                )
            }
            rows = connection.execute(
                """SELECT p.profile_id, p.label, p.grants_json, p.denies_json,
                    a.assignment_id, a.resource
                    FROM identity_profile_assignments a
                    JOIN identity_profiles p ON p.profile_id=a.profile_id
                    WHERE a.user_id=?""",
                (user.user_id,),
            ).fetchall()
        effective_roles = set(user.roles) | group_roles
        role = next(name for name in precedence if name in effective_roles)
        profiles = tuple(
            CapabilityProfile(
                profile_id=row["profile_id"], label=row["label"],
                grants=tuple(json.loads(row["grants_json"])), denies=tuple(json.loads(row["denies_json"])),
            )
            for row in rows
        )
        assignments = tuple(
            ProfileAssignment(
                assignment_id=row["assignment_id"], subject_id=user.user_id,
                profile_id=row["profile_id"], resource=row["resource"],
            )
            for row in rows
        )
        return DesignPolicyContext(
            subject_id=user.user_id,
            role=role,
            profiles=profiles,
            assignments=assignments,
            resource_rules=(),
        )

    def lesson_scopes(self, user_id: str) -> tuple[str, ...]:
        if set(self._effective_roles(user_id)) & {"owner", "administrator"}:
            return (
                "lesson.read", "lesson.audit", "lesson.edit", "lesson.disable", "lesson.supersede",
                "lesson.remove", "lesson.verify", "lesson.verification.record", "lesson.promote_global",
            )
        return ("lesson.read",)

    def _effective_roles(self, user_id: str) -> tuple[str, ...]:
        user = self.get_user(user_id)
        with self._connect() as connection:
            group_roles = tuple(
                row[0]
                for row in connection.execute(
                    """SELECT gr.role_name FROM identity_group_members gm
                        JOIN identity_group_roles gr ON gr.group_id=gm.group_id WHERE gm.user_id=?
                        ORDER BY gr.role_name""",
                    (user.user_id,),
                )
            )
        return tuple(dict.fromkeys((*user.roles, *group_roles)))

    def credential_scopes(self, user_id: str) -> tuple[str, ...]:
        scopes = ("identity.self", *self.lesson_scopes(user_id))
        if not set(self._effective_roles(user_id)) & {"owner", "administrator"}:
            return scopes
        return tuple(dict.fromkeys((*scopes, *MUTATION_SCOPES)))

    def browser_session_scopes(self, user_id: str) -> tuple[str, ...]:
        return self.credential_scopes(user_id)

    def cli_scopes(self, user_id: str, requested_scopes: tuple[str, ...]) -> tuple[str, ...]:
        requested = tuple(dict.fromkeys(requested_scopes))
        if any(scope not in MUTATION_SCOPES for scope in requested):
            raise PermissionError("requested CLI scope is not allowed")
        allowed = set(self.credential_scopes(user_id))
        if any(scope not in allowed for scope in requested):
            raise PermissionError("requested CLI scope is not allowed")
        task_submission = ("agent.launch",) if "agent.launch" in allowed else ()
        return tuple(dict.fromkeys((*self.lesson_scopes(user_id), *task_submission, *requested)))

    def _purpose_scopes(
        self,
        user: IdentityUser,
        kind: CredentialKind,
        purpose: str | None,
    ) -> tuple[str, ...]:
        if (
            purpose == VERIFIER_SERVICE_PURPOSE
            and kind is CredentialKind.service
            and user.normalized_username == VERIFIER_SERVICE_USERNAME
        ):
            return VERIFIER_SERVICE_SCOPES
        return ()

    def issue_service_credential_for_purpose(self, user_id: str, purpose: str) -> IssuedCredential:
        user = self.get_user(user_id)
        scopes = self._purpose_scopes(user, CredentialKind.service, purpose)
        if not scopes:
            raise PermissionError("service credential purpose is not allowed")
        return self.issue_credential(
            user_id,
            CredentialKind.service,
            "local lesson verifier",
            scopes,
            _purpose=purpose,
        )

    @staticmethod
    def require_distinct_accounts(*user_ids: str) -> None:
        if len(set(user_ids)) != len(user_ids):
            raise PermissionError("global promotion requires distinct accounts")

    def _token_digest(self, token: str) -> str:
        return hmac.new(self._hmac_key, token.encode("utf-8"), hashlib.sha256).hexdigest()

    def _audit(
        self,
        operation: str,
        *,
        actor_id: str | None,
        target_id: str | None,
        reason: str,
        changed_fields: dict[str, object] | None = None,
    ) -> None:
        created_at = self._iso(self._now())
        previous_hash = self.audit_anchor_path.read_text("ascii").strip() if self.audit_anchor_path.exists() else ""
        payload = json.dumps(
            {
                "actor_id": actor_id,
                "target_id": target_id,
                "operation": operation,
                "changed_fields": changed_fields or {},
                "reason": reason,
                "created_at": created_at,
                "previous_hash": previous_hash,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        entry_hash = hmac.new(self._hmac_key, payload.encode("utf-8"), hashlib.sha256).hexdigest()
        with self._connect() as connection:
            connection.execute(
                """INSERT INTO identity_audit(
                    audit_id, actor_id, target_id, operation, changed_fields_json, reason,
                    previous_hash, entry_hash, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    str(uuid4()), actor_id, target_id, operation,
                    json.dumps(changed_fields or {}, sort_keys=True), reason,
                    previous_hash or None, entry_hash, created_at,
                ),
            )
        temporary = self.audit_anchor_path.with_suffix(".anchor.tmp")
        temporary.write_text(entry_hash, encoding="ascii")
        temporary.replace(self.audit_anchor_path)

    def issue_credential(
        self,
        user_id: str,
        kind: CredentialKind | str,
        label: str,
        scopes: tuple[str, ...],
        *,
        lifetime: timedelta | None = None,
        _purpose: str | None = None,
    ) -> IssuedCredential:
        user = self.get_user(user_id)
        if user.status != "active":
            raise PermissionError("user is disabled")
        credential_kind = CredentialKind(kind)
        purpose_scopes = self._purpose_scopes(user, credential_kind, _purpose)
        if _purpose and not purpose_scopes:
            raise PermissionError("credential purpose is not allowed")
        now = self._now()
        with self._connect() as connection:
            state = connection.execute(
                """SELECT mode, development_credentials_permanent
                    FROM identity_bootstrap_state WHERE singleton=1"""
            ).fetchone()
        permanent_development = bool(
            state and state["mode"] == "development" and state["development_credentials_permanent"]
        )
        if permanent_development:
            lifetime = timedelta(days=36_500)
        else:
            lifetime = lifetime or timedelta(days=30)
        expires_at = now + lifetime
        idle_expires_at = None if permanent_development else (now + timedelta(hours=12) if credential_kind is CredentialKind.browser_session else None)
        token = secrets.token_urlsafe(48)
        credential_id = str(uuid4())
        normalized_scopes = purpose_scopes or tuple(dict.fromkeys(scopes))
        with self._connect() as connection:
            connection.execute(
                """INSERT INTO identity_sessions(
                    credential_id, user_id, kind, label, credential_purpose, token_hash, scopes_json, issued_at,
                    expires_at, idle_expires_at, last_used_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    credential_id, user_id, credential_kind.value, label.strip(), _purpose, self._token_digest(token),
                    json.dumps(normalized_scopes), self._iso(now), self._iso(expires_at),
                    self._iso(idle_expires_at) if idle_expires_at else None, self._iso(now),
                ),
            )
        self._audit(
            "credential.issued",
            actor_id=user_id,
            target_id=credential_id,
            reason="credential issued",
            changed_fields={"kind": credential_kind.value, "label": label, "scopes": normalized_scopes},
        )
        return IssuedCredential(
            credential_id=credential_id,
            user_id=user_id,
            kind=credential_kind,
            label=label,
            scopes=normalized_scopes,
            issued_at=now,
            expires_at=expires_at,
            idle_expires_at=idle_expires_at,
            token=token,
        )

    def resolve_credential(
        self,
        raw_token: str,
        *,
        required_kind: CredentialKind | str | None = None,
        required_scope: str | None = None,
    ) -> AuthenticatedPrincipal:
        token_hash = self._token_digest(raw_token)
        with self._connect() as connection:
            row = connection.execute(
                """SELECT s.*, u.username, u.status FROM identity_sessions s
                    JOIN identity_users u ON u.user_id=s.user_id WHERE s.token_hash=?""",
                (token_hash,),
            ).fetchone()
            if not row:
                raise PermissionError("invalid credential")
            if row["revoked_at"]:
                raise PermissionError("credential is revoked")
            if row["status"] != "active":
                raise PermissionError("user is disabled")
            now = self._now()
            if datetime.fromisoformat(row["expires_at"]) <= now:
                raise PermissionError("credential is expired")
            if row["idle_expires_at"] and datetime.fromisoformat(row["idle_expires_at"]) <= now:
                raise PermissionError("credential is expired")
            kind = CredentialKind(row["kind"])
            if required_kind is not None and kind is not CredentialKind(required_kind):
                raise PermissionError("credential kind is not allowed")
            stored_scopes = tuple(json.loads(row["scopes_json"]))
            if kind is CredentialKind.browser_session:
                next_idle = min(now + timedelta(hours=12), datetime.fromisoformat(row["expires_at"]))
                connection.execute(
                    "UPDATE identity_sessions SET last_used_at=?, idle_expires_at=? WHERE credential_id=?",
                    (self._iso(now), self._iso(next_idle), row["credential_id"]),
                )
            else:
                connection.execute(
                    "UPDATE identity_sessions SET last_used_at=? WHERE credential_id=?",
                    (self._iso(now), row["credential_id"]),
                )
        user = self.get_user(row["user_id"])
        purpose_scopes = self._purpose_scopes(user, kind, row["credential_purpose"])
        allowed_scopes = set(purpose_scopes or self.credential_scopes(user.user_id))
        scopes = tuple(scope for scope in stored_scopes if scope in allowed_scopes)
        if required_scope and required_scope not in scopes:
            raise PermissionError("credential scope is not allowed")
        return AuthenticatedPrincipal(
            user_id=user.user_id,
            username=user.username,
            roles=user.roles,
            credential_id=row["credential_id"],
            credential_kind=kind.value,
            scopes=scopes,
            authentication_source=kind.value,
        )

    def revoke_credential(self, credential_id: str, *, actor_id: str | None, reason: str) -> None:
        now = self._iso(self._now())
        with self._connect() as connection:
            changed = connection.execute(
                "UPDATE identity_sessions SET revoked_at=COALESCE(revoked_at, ?) WHERE credential_id=?",
                (now, credential_id),
            ).rowcount
        if not changed:
            raise KeyError(credential_id)
        self._audit("credential.revoked", actor_id=actor_id, target_id=credential_id, reason=reason)

    def revoke_kind(self, user_id: str, kind: CredentialKind | str, *, actor_id: str | None, reason: str) -> int:
        now = self._iso(self._now())
        with self._connect() as connection:
            changed = connection.execute(
                "UPDATE identity_sessions SET revoked_at=? WHERE user_id=? AND kind=? AND revoked_at IS NULL",
                (now, user_id, CredentialKind(kind).value),
            ).rowcount
        self._audit(
            "credential.kind_revoked", actor_id=actor_id, target_id=user_id, reason=reason,
            changed_fields={"kind": CredentialKind(kind).value, "count": changed},
        )
        return changed

    def revoke_user_credentials(self, user_id: str, *, actor_id: str | None, reason: str) -> int:
        now = self._iso(self._now())
        with self._connect() as connection:
            changed = connection.execute(
                "UPDATE identity_sessions SET revoked_at=? WHERE user_id=? AND revoked_at IS NULL",
                (now, user_id),
            ).rowcount
        if changed:
            self._audit(
                "credential.user_revoked", actor_id=actor_id, target_id=user_id, reason=reason,
                changed_fields={"count": changed},
            )
        return changed
