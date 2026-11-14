from __future__ import annotations

import json
import os
import re
import uuid
from pathlib import Path

from web_app.models import SkillsetMember, SkillsetRecord
from web_app.skills import SkillLibraryService


CATEGORIES = (
    ("coding", "Coding", ("code", "coding", "python", "javascript", "typescript", "develop", "debug", "refactor", "api", "git"), (".py", ".js", ".ts", ".tsx", ".jsx")),
    ("testing-review", "Testing and Review", ("test", "testing", "review", "debug", "audit", "verify", "quality"), ()),
    ("browser-ui", "Browser and UI", ("browser", "chrome", "ui", "ux", "frontend", "react", "accessibility"), (".html", ".css")),
    ("documents", "Documents", ("document", "docx", "pdf", "pptx", "slides", "xlsx", "spreadsheet", "markdown"), (".docx", ".pdf", ".pptx", ".xlsx", ".md")),
    ("data-ai", "Data and AI", ("ai", "model", "llm", "data", "dataset", "embedding", "huggingface"), (".csv", ".json", ".jsonl")),
    ("cloud-delivery", "Cloud and Delivery", ("cloud", "deploy", "docker", "kubernetes", "vercel", "terraform", "ci", "delivery"), (".yml", ".yaml")),
    ("security", "Security", ("security", "secure", "owasp", "vulnerability", "threat"), ()),
    ("planning", "Planning", ("plan", "spec", "requirements", "workflow", "brainstorm", "project"), ()),
    ("integrations", "Integrations", ("jira", "confluence", "slack", "google", "atlassian", "connector", "mcp"), ()),
)


def _tokens(value: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", value.casefold()))


class SkillsetService:
    def __init__(self, data_root: Path, library: SkillLibraryService) -> None:
        self.path = Path(data_root).resolve() / "skillsets.json"
        self.library = library

    def _stored(self) -> list[SkillsetRecord]:
        if not self.path.is_file():
            return []
        return [SkillsetRecord.model_validate(item) for item in json.loads(self.path.read_text(encoding="utf-8"))]

    def list(self) -> list[SkillsetRecord]:
        return [item for item in self._stored() if item.members]

    def reconcile(self) -> list[SkillsetRecord]:
        existing = {item.id: item for item in self._stored()}
        members: dict[str, list[SkillsetMember]] = {item[0]: [] for item in CATEGORIES}
        for pack in self.library.list():
            for skill in pack.skills:
                if not skill.enabled:
                    continue
                words = _tokens(f"{skill.name} {skill.description}")
                for category_id, _name, terms, _extensions in CATEGORIES:
                    if words.intersection(terms):
                        members[category_id].append(SkillsetMember(
                            reference=f"{pack.id}:{skill.id}",
                            name=skill.name,
                        ))
        records: list[SkillsetRecord] = []
        for category_id, name, terms, extensions in CATEGORIES:
            prior = existing.get(category_id)
            category_members = sorted(members[category_id], key=lambda item: (item.name.casefold(), item.reference))
            records.append(SkillsetRecord(
                id=category_id,
                name=name,
                category=category_id,
                members=category_members,
                routing_terms=list(terms),
                attachment_extensions=list(extensions),
                summary=f"{len(category_members)} skills for {name.casefold()} workflows.",
                enabled=prior.enabled if prior else True,
                auto_attach=prior.auto_attach if prior else True,
            ))
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.parent / f".skillsets-{uuid.uuid4().hex}.tmp"
        temporary.write_text(json.dumps([item.model_dump(mode="json") for item in records], indent=2), encoding="utf-8")
        os.replace(temporary, self.path)
        return [item for item in records if item.members]
