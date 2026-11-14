from __future__ import annotations

import re
from pathlib import Path

from web_app.models import SessionRecord, SkillRecommendation, SkillRecommendationResult
from web_app.settings import SettingsService
from web_app.skills import SkillLibraryService
from web_app.skillsets import SkillsetService


GENERIC_TERMS = frozenset({"help", "task", "skill", "use", "create", "build", "make", "work", "project"})
PROVIDER_TERMS = frozenset({"claude", "cursor", "copilot", "gemini", "anthropic"})
ROUTING_SYNONYMS = {
    "bug": "debug",
    "fix": "debug",
    "website": "browser",
    "web": "browser",
    "spreadsheet": "xlsx",
    "slides": "pptx",
    "document": "docx",
    "release": "deploy",
}


def _tokens(value: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", value.casefold()))


def _stem(value: str) -> str:
    for suffix in ("ing", "ed", "es", "s"):
        if value.endswith(suffix) and len(value) - len(suffix) >= 4:
            return value[:-len(suffix)]
    return value


class SkillRecommendationService:
    def __init__(self, library: SkillLibraryService, skillsets: SkillsetService, settings: SettingsService) -> None:
        self.library = library
        self.skillsets = skillsets
        self.settings = settings

    def recommend(self, session: SessionRecord, prompt: str) -> SkillRecommendationResult:
        session.excluded_skill_ids = list(dict.fromkeys(session.excluded_skill_ids))
        packs = self.library.list()
        skills = {
            f"{pack.id}:{skill.id}": skill
            for pack in packs for skill in pack.skills if skill.enabled
        }
        manual: list[SkillRecommendation] = []
        for reference in dict.fromkeys(session.selected_skill_ids):
            skill = skills.get(reference)
            if skill:
                manual.append(SkillRecommendation(
                    reference=reference, name=skill.name, score=1000,
                    reasons=["selected manually"], manual=True,
                ))
        routing = self.settings.get().skill_routing
        if not session.auto_attach_skills or not routing.auto_attach:
            return SkillRecommendationResult(recommendations=manual)

        prompt_tokens = _tokens(prompt)
        if not prompt_tokens or prompt_tokens.issubset(GENERIC_TERMS):
            return SkillRecommendationResult(recommendations=manual)
        expanded = prompt_tokens | {ROUTING_SYNONYMS[token] for token in prompt_tokens if token in ROUTING_SYNONYMS}
        prompt_stems = {_stem(token) for token in expanded}
        suffixes = {Path(item.display_name).suffix.casefold() for item in session.attachments if item.included}
        sets = self.skillsets.reconcile()
        memberships: dict[str, list] = {}
        for skillset in sets:
            if not skillset.enabled or not skillset.auto_attach:
                continue
            for member in skillset.members:
                memberships.setdefault(member.reference, []).append(skillset)

        candidates: list[SkillRecommendation] = []
        excluded = set(session.excluded_skill_ids)
        manual_refs = {item.reference for item in manual}
        for reference, skill in skills.items():
            if reference in excluded or reference in manual_refs:
                continue
            score = 0
            reasons: list[str] = []
            name_tokens = _tokens(skill.name)
            description_tokens = _tokens(skill.description)
            capability_match = re.search(r"(?mi)^(?:capabilities|required-capabilities):\s*([^\n]+)", skill.content)
            capability_tokens = _tokens(capability_match.group(1)) if capability_match else set()
            name_hits = sorted(prompt_tokens & name_tokens)
            capability_hits = sorted(prompt_tokens & capability_tokens)
            description_hits = sorted(prompt_tokens & description_tokens)
            if name_hits:
                score += 8
                reasons.append(f"name: {name_hits[0]}")
            if capability_hits:
                score += 6
                reasons.append(f"capability: {capability_hits[0]}")
            if description_hits:
                score += 4
                reasons.append(f"description: {description_hits[0]}")
            exact_tokens = name_tokens | capability_tokens | description_tokens
            fuzzy_hits = sorted(token for token in prompt_stems if token not in prompt_tokens and token in {_stem(item) for item in exact_tokens})
            if fuzzy_hits:
                score += 2
                reasons.append(f"related: {fuzzy_hits[0]}")
            matched_sets: list[str] = []
            attachment_hit = None
            for skillset in memberships.get(reference, []):
                if not attachment_hit:
                    attachment_hit = next((ext for ext in skillset.attachment_extensions if ext in suffixes), None)
                if expanded.intersection(skillset.routing_terms):
                    matched_sets.append(skillset.id)
            if attachment_hit:
                score += 8
                reasons.append(f"attachment: {attachment_hit}")
            if matched_sets:
                score += 3
                reasons.append(f"skillset: {sorted(matched_sets)[0]}")
            if not skill.description.strip():
                score -= 2
            content_tokens = _tokens(skill.original_content or skill.content)
            if content_tokens.intersection(PROVIDER_TERMS):
                score -= 6
                reasons.append("provider-only penalty")
            if score < routing.minimum_score:
                continue
            candidates.append(SkillRecommendation(
                reference=reference,
                name=skill.name,
                score=score,
                reasons=reasons,
                skillset_ids=sorted({item.id for item in memberships.get(reference, [])}),
            ))
        candidates.sort(key=lambda item: (-item.score, item.reference))
        remaining = max(0, routing.max_skills - len(manual))
        chosen: list[SkillRecommendation] = []
        chosen_sets: list[str] = []
        for item in candidates:
            relevant_sets = [value for value in item.skillset_ids if value in chosen_sets or len(chosen_sets) < routing.max_skillsets]
            if item.skillset_ids and not relevant_sets:
                continue
            for value in relevant_sets:
                if value not in chosen_sets and len(chosen_sets) < routing.max_skillsets:
                    chosen_sets.append(value)
            chosen.append(item)
            if len(chosen) >= remaining:
                break
        return SkillRecommendationResult(recommendations=manual + chosen, skillset_ids=chosen_sets)
