from __future__ import annotations

import hashlib
import hmac
import re
import secrets
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from web_app.models import (
    ActionApprovalResult,
    ActionProposal,
    ActionSuggestion,
    ApprovedAction,
)


NORMAL_TOKEN_SECONDS = 300
DESTRUCTIVE_TOKEN_SECONDS = 60
KNOWN_COMMANDS = {
    "cmd", "git", "node", "npm", "npx", "pip", "pip3", "powershell", "pwsh", "py",
    "pytest", "python", "python3", "rg", "write-output",
}
DESTRUCTIVE_PATTERNS = (
    re.compile(r"(?i)(?:^|[;&|]\s*)(?:rm|del|erase|rmdir|rd)\b"),
    re.compile(r"(?i)\bremove-item\b"),
    re.compile(r"(?i)\b(?:format|diskpart|shutdown|stop-computer)\b"),
    re.compile(r"(?i)\bgit\s+(?:reset\s+--hard|clean\s+-[a-z]*f)\b"),
    re.compile(r"(?i)\b(?:drop|truncate)\s+(?:database|table)\b"),
)


@dataclass
class _TokenRecord:
    digest: str
    expires_at: float
    terminal_id: str
    fingerprint: str


class ActionProposalService:
    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._proposals: dict[str, ActionProposal] = {}
        self._tokens: dict[str, _TokenRecord] = {}
        self._lock = threading.RLock()

    def propose(
        self,
        session_id: str,
        suggestions: list[ActionSuggestion],
        source_skill_ids: list[str],
        default_cwd: str,
    ) -> list[ActionProposal]:
        with self._lock:
            for proposal in self._proposals.values():
                if proposal.session_id == session_id and proposal.status in {
                    "pending", "awaiting_confirmation", "approved"
                }:
                    proposal.status = "superseded"
                    self._tokens.pop(proposal.id, None)
            return [
                self._create(session_id, suggestion, source_skill_ids, default_cwd)
                for suggestion in suggestions[:5]
            ]

    def _create(
        self,
        session_id: str,
        suggestion: ActionSuggestion,
        source_skill_ids: list[str],
        default_cwd: str,
    ) -> ActionProposal:
        command = suggestion.command.strip()
        cwd = str(Path((suggestion.cwd or default_cwd).strip()).expanduser().resolve())
        explanation = suggestion.explanation.strip()
        risk, reason = self._classify(command)
        proposal = ActionProposal(
            id=uuid.uuid4().hex,
            session_id=session_id,
            command=command,
            cwd=cwd,
            explanation=explanation,
            source_skill_ids=list(dict.fromkeys(source_skill_ids)),
            risk=risk,
            risk_reason=reason,
        )
        self._proposals[proposal.id] = proposal
        return proposal

    @staticmethod
    def _classify(command: str) -> tuple[str, str]:
        for pattern in DESTRUCTIVE_PATTERNS:
            if pattern.search(command):
                return "destructive", "Matched a destructive pattern"
        match = re.match(r"\s*([A-Za-z0-9_.-]+)", command)
        executable = (match.group(1) if match else "").casefold()
        if executable.endswith(".exe"):
            executable = executable[:-4]
        if executable not in KNOWN_COMMANDS:
            return "destructive", "Conservatively classified as destructive: unknown command"
        return "normal", "Known command without a destructive pattern"

    def get(self, session_id: str, proposal_id: str) -> ActionProposal:
        with self._lock:
            proposal = self._proposals.get(proposal_id)
            if proposal is None:
                raise KeyError(proposal_id)
            if proposal.session_id != session_id:
                raise PermissionError("Proposal belongs to a different session")
            return proposal

    def approve(self, session_id: str, proposal_id: str, terminal_id: str) -> ActionApprovalResult:
        with self._lock:
            proposal = self.get(session_id, proposal_id)
            if proposal.status not in {"pending", "awaiting_confirmation"}:
                raise PermissionError("Proposal is no longer approvable")
            self._tokens.pop(proposal.id, None)
            if proposal.risk == "destructive":
                proposal.status = "awaiting_confirmation"
                proposal.confirmation_phrase = f"RUN {proposal.id[:8].upper()}"
                return ActionApprovalResult(
                    proposal_id=proposal.id,
                    requires_confirmation=True,
                    confirmation_phrase=proposal.confirmation_phrase,
                )
            return self._issue_token(proposal, terminal_id, NORMAL_TOKEN_SECONDS)

    def confirm_destructive(
        self,
        session_id: str,
        proposal_id: str,
        terminal_id: str,
        phrase: str,
    ) -> ActionApprovalResult:
        with self._lock:
            proposal = self.get(session_id, proposal_id)
            if proposal.status != "awaiting_confirmation" or not proposal.confirmation_phrase:
                raise PermissionError("Destructive confirmation was not requested")
            if not hmac.compare_digest(phrase, proposal.confirmation_phrase):
                raise PermissionError("Confirmation phrase does not match")
            return self._issue_token(proposal, terminal_id, DESTRUCTIVE_TOKEN_SECONDS)

    def _issue_token(
        self,
        proposal: ActionProposal,
        terminal_id: str,
        lifetime: int,
    ) -> ActionApprovalResult:
        token = secrets.token_urlsafe(32)
        self._tokens[proposal.id] = _TokenRecord(
            digest=self._token_digest(token),
            expires_at=self._clock() + lifetime,
            terminal_id=terminal_id,
            fingerprint=self._fingerprint(proposal),
        )
        proposal.status = "approved"
        return ActionApprovalResult(
            proposal_id=proposal.id,
            token=token,
            expires_in=lifetime,
        )

    def consume(self, proposal_id: str, token: str, terminal_id: str) -> ApprovedAction:
        with self._lock:
            proposal = self._proposals.get(proposal_id)
            record = self._tokens.get(proposal_id)
            if proposal is None or record is None or proposal.status != "approved":
                raise PermissionError("Action approval is unavailable")
            if self._clock() > record.expires_at:
                self._tokens.pop(proposal_id, None)
                raise PermissionError("Action approval has expired")
            if not hmac.compare_digest(record.terminal_id, terminal_id):
                raise PermissionError("Action approval is bound to a different terminal")
            if not hmac.compare_digest(record.digest, self._token_digest(token)):
                raise PermissionError("Action approval token is invalid")
            if not hmac.compare_digest(record.fingerprint, self._fingerprint(proposal)):
                self._tokens.pop(proposal_id, None)
                raise PermissionError("Action proposal changed after approval")
            self._tokens.pop(proposal_id, None)
            proposal.status = "consumed"
            return ApprovedAction(proposal_id=proposal.id, command=proposal.command, cwd=proposal.cwd)

    def reject(self, session_id: str, proposal_id: str) -> ActionProposal:
        with self._lock:
            proposal = self.get(session_id, proposal_id)
            proposal.status = "rejected"
            self._tokens.pop(proposal.id, None)
            return proposal

    def edit(
        self,
        session_id: str,
        proposal_id: str,
        suggestion: ActionSuggestion,
    ) -> ActionProposal:
        with self._lock:
            proposal = self.get(session_id, proposal_id)
            proposal.status = "superseded"
            self._tokens.pop(proposal.id, None)
            return self._create(
                session_id,
                suggestion,
                proposal.source_skill_ids,
                proposal.cwd,
            )

    @staticmethod
    def _token_digest(token: str) -> str:
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    @staticmethod
    def _fingerprint(proposal: ActionProposal) -> str:
        value = f"{proposal.session_id}\0{proposal.command}\0{proposal.cwd}"
        return hashlib.sha256(value.encode("utf-8")).hexdigest()
