from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import json
from pathlib import Path
import sqlite3

from web_app.core.cli_identity import DpapiTokenStore
from web_app.core.identity import AuthenticatedPrincipal, IdentityService


VERIFIER_USERNAME = "json-codr-verifier"
VERIFIER_SCOPES = ("lesson.verify", "lesson.verification.record")


@dataclass(frozen=True)
class VerificationIdentityRecord:
    lesson_id: str
    author_id: str
    actor_id: str
    verifier_id: str
    outcome: str
    created_at: str


class VerifierIdentityService:
    def __init__(self, identity: IdentityService, data_root: Path):
        self.identity = identity
        self.data_root = Path(data_root)
        self.store = DpapiTokenStore(self.data_root / "core" / "verifier.service.dpapi")
        self.database_path = self.data_root / "core" / "verifier.sqlite"
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.database_path)
        try:
            connection.execute(
                """CREATE TABLE IF NOT EXISTS lesson_verifications (
                    lesson_id TEXT NOT NULL, author_id TEXT NOT NULL, actor_id TEXT NOT NULL,
                    verifier_id TEXT NOT NULL, outcome TEXT NOT NULL, evidence_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )"""
            )
            connection.commit()
        finally:
            connection.close()

    def ensure_service_account(self) -> AuthenticatedPrincipal:
        user = next(
            (candidate for candidate in self.identity.list_users() if candidate.normalized_username == VERIFIER_USERNAME),
            None,
        )
        if user is None:
            user = self.identity.create_user(VERIFIER_USERNAME, "JSON_CODR Verifier", roles=("viewer",))
        try:
            return self.status()
        except PermissionError:
            credential = self.identity.issue_credential(
                user.user_id,
                "service",
                "local lesson verifier",
                VERIFIER_SCOPES,
            )
            self.store.save(credential)
            return self.identity.resolve_credential(credential.token, required_kind="service")

    def status(self) -> AuthenticatedPrincipal:
        document = self.store.load()
        principal = self.identity.resolve_credential(document["token"], required_kind="service")
        if tuple(principal.scopes) != VERIFIER_SCOPES:
            raise PermissionError("verifier service credential has invalid scopes")
        return principal

    def automatic_lesson_activation_ready(self) -> bool:
        try:
            self.status()
            return True
        except PermissionError:
            return False

    def record_verification(
        self,
        lesson_id: str,
        *,
        author_id: str,
        actor_id: str,
        outcome: str,
        evidence: dict[str, object],
    ) -> VerificationIdentityRecord:
        principal = self.status()
        self.identity.require_distinct_accounts(author_id, actor_id, principal.user_id)
        created_at = datetime.now(UTC).isoformat()
        connection = sqlite3.connect(self.database_path)
        try:
            connection.execute(
                """INSERT INTO lesson_verifications(
                    lesson_id, author_id, actor_id, verifier_id, outcome, evidence_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (lesson_id, author_id, actor_id, principal.user_id, outcome, json.dumps(evidence), created_at),
            )
            connection.commit()
        finally:
            connection.close()
        return VerificationIdentityRecord(
            lesson_id, author_id, actor_id, principal.user_id, outcome, created_at
        )
