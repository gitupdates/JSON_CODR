# Automatic Skillsets V1.0.4 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship JSON_CODR V1.0.4 with reference-based Skillset packs, deterministic automatic skill recommendation and attachment, compressed prompt context, and confirmed skill-originated terminal actions.

**Architecture:** Add focused services for Skillset reconciliation/routing and ephemeral action approvals while keeping `app.py` endpoints thin. Manual and automatic skills merge in a bounded `ContextAssembler`; the browser renders recommendation reasons and action proposals but the backend revalidates all references and authorization.

**Tech Stack:** Python 3, FastAPI, Pydantic v2, vanilla JavaScript/CSS, unittest/pytest-compatible tests, Ollama structured JSON, Windows PowerShell terminal service.

**Spec:** `docs/superpowers/specs/2026-11-13-automatic-skillsets-design.md`

## Global Constraints

- Use deterministic local routing only; no new dependency, cloud API, embeddings, or model-based router.
- Generated Skillsets reference canonical `pack_id:skill_id` members and never copy stored instructions.
- Automatic attachment is capped at three Skillsets, five distinct skills, and 12,000 skill-context characters.
- Total non-user context is capped at 20,000 characters; attachments receive at least 8,000 when present and the full user prompt is always preserved.
- Model prose and fenced code never become actions; only validated structured `actions` fields may create proposals.
- Normal proposals require one approval; destructive or unknown commands require typed second confirmation and a 60-second one-shot token.
- Proposals are memory-only, chat-session scoped, terminal-bound at final approval, and invalidated by restart, rejection, edits, supersession, or consumption.
- Existing direct terminal input and prerequisite installation remain separate user/trusted workflows.
- Release identifiers, settings defaults/migrations, UI labels, launcher text, API metadata, and documentation all become `V1.0.4`.
- Preserve the unrelated active `~$README.md` Word lock file and never stage or remove it.

## Review Focus

- Prompts made only of generic words must attach no skill instead of flooding the model; Task 2 tests the threshold and generic penalty.
- Deleted, disabled, duplicated, or stale skill references must disappear during reconciliation and never reach context; Tasks 1 and 3 test this.
- Large skills plus large attachments must respect the shared 20,000-character ceiling without cutting an instruction mid-document; Task 3 tests boundary allocation.
- Altered, expired, replayed, cross-session, and cross-terminal action approvals must fail closed; Task 4 tests every case.
- A malformed or adversarial model `actions` field must not block the textual answer or reach the terminal; Task 4 tests validation and isolation.

---

### Task 1: Reference-based Skillset catalog and settings

**Files:**
- Create: `web_app/skillsets.py`
- Modify: `web_app/models.py`
- Modify: `web_app/settings.py`
- Modify: `web_app/app.py`
- Create: `test_skillsets.py`
- Modify: `test_settings.py`

**Interfaces:**
- Consumes: `SkillLibraryService.list() -> list[SkillPack]`.
- Produces: `SkillsetRecord`, `SkillRoutingSettings`, `SkillsetService.list() -> list[SkillsetRecord]`, `SkillsetService.reconcile() -> list[SkillsetRecord]`, `GET /api/skillsets`, and persisted `settings.skill_routing`.

- [ ] **Step 1: Write failing catalog tests** for stable generated IDs/categories, reference-only membership, multi-category membership, stale/disabled member removal, user-owned `enabled`/`auto_attach` persistence, and atomic `skillsets.json` writes.
- [ ] **Step 2: Run `python -m unittest -v test_skillsets.py`** and verify failure is caused by missing Skillset models/service.
- [ ] **Step 3: Implement models** `SkillsetRecord`, `SkillsetMember`, and `SkillRoutingSettings(auto_attach=True, max_skillsets=3, max_skills=5, minimum_score=8)` in `web_app/models.py`.
- [ ] **Step 4: Implement `SkillsetService(data_root: Path, library: SkillLibraryService)`** with deterministic categories, stable IDs, reference-only persistence, atomic replacement, and reconciliation rules from the spec.
- [ ] **Step 5: Migrate `SystemSettings.version` from 1 to 2 and add `skill_routing` update support** while preserving unknown fields and explicit-null validation.
- [ ] **Step 6: Add `GET /api/skillsets`** and call reconciliation after install, remove, deduplicate, and skill update operations.
- [ ] **Step 7: Run `python -m unittest -v test_skillsets.py test_settings.py test_skills.py`** and verify all tests pass.
- [ ] **Step 8: Commit** with `feat(skillsets): add reference-based skillset catalog`.

### Task 2: Deterministic recommendation engine and session controls

**Files:**
- Create: `web_app/recommendations.py`
- Modify: `web_app/models.py`
- Modify: `web_app/workspace.py`
- Modify: `web_app/app.py`
- Create: `test_recommendations.py`
- Modify: `test_workspace.py`

**Interfaces:**
- Consumes: `SkillsetService.list()`, enabled `SkillRecord`s, prompt text, and attachment metadata.
- Produces: `SkillRecommendationService.recommend(session: SessionRecord, prompt: str) -> SkillRecommendationResult`, `SkillRecommendation`, `SessionRecord.auto_attach_skills`, `SessionRecord.excluded_skill_ids`, and `POST /api/sessions/{session_id}/skill-recommendations`.

- [ ] **Step 1: Write failing scoring tests** pinning every weight, the conservative stemmer, checked-in synonyms, stable tie ordering, minimum score 8, generic-only suppression, provider-only penalty, attachment extension/type signals, three-Set/five-skill caps, manual priority, and session exclusions.
- [ ] **Step 2: Write failing API/session tests** for preview reasons, default migration, disabling auto-attach, rejecting nonexistent exclusions, and recalculation after a skill is removed.
- [ ] **Step 3: Run `python -m unittest -v test_recommendations.py test_workspace.py`** and verify the new interfaces are absent.
- [ ] **Step 4: Implement normalization/scoring** in `SkillRecommendationService` using the exact policy in the design and a module-level immutable routing vocabulary.
- [ ] **Step 5: Extend session persistence** with `auto_attach_skills: bool = True` and deduplicated `excluded_skill_ids: list[str]`, migrating schema-1 manifests without data loss.
- [ ] **Step 6: Add recommendation preview/session-update APIs** with server-side validation of enabled, existing references.
- [ ] **Step 7: Run `python -m unittest -v test_recommendations.py test_workspace.py test_skills.py`** and verify all tests pass.
- [ ] **Step 8: Commit** with `feat(skills): recommend relevant skills deterministically`.

### Task 3: Automatic attachment and compressed context

**Files:**
- Modify: `web_app/context.py`
- Modify: `web_app/app.py`
- Modify: `web_app/models.py`
- Modify: `test_context.py`
- Modify: `test_web_api.py`

**Interfaces:**
- Consumes: `SkillRecommendationResult` from Task 2 and manual `selected_skill_ids`.
- Produces: `ContextBuildResult(prompt: str, attached_skills: list[AttachedSkill], skillsets: list[str], omitted: list[str])` from `ContextAssembler.build(...)`; `ChatResult.attached_skills`, `attached_skillsets`, and `skill_recommendations`.

- [ ] **Step 1: Write failing context tests** for manual-first merge, automatic deduplication, one shared envelope, removal of repeated compatibility/envelope text, stale/disabled skip, whole-skill truncation, 12,000 skill cap, guaranteed 8,000 attachment allocation, 20,000 combined ceiling, and full user prompt preservation.
- [ ] **Step 2: Write failing chat API tests** proving backend recalculation overrides stale client recommendations and response metadata explains attached skills.
- [ ] **Step 3: Run `python -m unittest -v test_context.py test_web_api.py`** and verify failures describe the missing result model and router integration.
- [ ] **Step 4: Replace `build_prompt` internals with `build`** returning `ContextBuildResult`; keep `build_prompt` as a compatibility wrapper for existing callers/tests.
- [ ] **Step 5: Integrate recommendations in `/api/chat`** before Ollama invocation and populate attachment/reason metadata on every success path, including archive conversion.
- [ ] **Step 6: Run `python -m unittest -v test_context.py test_web_api.py test_attachments_api.py`** and verify all tests pass.
- [ ] **Step 7: Commit** with `feat(context): attach and compress recommended skills`.

### Task 4: Structured action proposals and two-stage terminal approval

**Files:**
- Create: `web_app/actions.py`
- Modify: `cli.py`
- Modify: `web_app/models.py`
- Modify: `web_app/ollama_service.py`
- Modify: `web_app/app.py`
- Modify: `web_app/terminal.py`
- Create: `test_actions.py`
- Modify: `test_terminal.py`
- Modify: `test_web_api.py`

**Interfaces:**
- Consumes: structured `ActionSuggestion(command, cwd, explanation)` values from Ollama and current session/skill metadata.
- Produces: `ActionProposalService`, `ActionProposal`, `POST .../approve`, `POST .../confirm-destructive`, `POST .../reject`, and WebSocket `{type:"approved_action", proposal_id, token}` consumption.

- [ ] **Step 1: Write failing proposal tests** for structured-field-only creation, command/cwd normalization, conservative destructive classification, unknown-command classification, session ownership, five-minute normal token, typed phrase, 60-second destructive token, terminal binding, rejection/edit/supersession invalidation, expiry, replay, restart, and thread-safe one-shot consumption.
- [ ] **Step 2: Write failing Ollama/API tests** proving arbitrary prose/fenced commands create no proposal, invalid action entries are omitted without losing valid text, and a model cannot supply its own approval/risk fields.
- [ ] **Step 3: Write failing terminal tests** proving direct user input still works while `approved_action` requires an exact valid token and writes only the stored server-side command.
- [ ] **Step 4: Run `python -m unittest -v test_actions.py test_terminal.py test_web_api.py`** and verify the proposal service and action schema are missing.
- [ ] **Step 5: Extend `StructuredCLIResponse` and `ChatResult`** with bounded `actions: list[ActionSuggestion]`; validate length, command size, cwd, control characters, and drop invalid suggestions server-side.
- [ ] **Step 6: Implement `ActionProposalService`** with monotonic expiry, cryptographically random tokens, exact hashes, locks, session ownership, risk classification, and one-shot consumption.
- [ ] **Step 7: Add proposal endpoints and guarded WebSocket action handling**; never accept a command string from the WebSocket action message.
- [ ] **Step 8: Run `python -m unittest -v test_actions.py test_terminal.py test_web_api.py`** and verify all tests pass.
- [ ] **Step 9: Commit** with `feat(actions): require confirmed skill terminal actions`.

### Task 5: Skillset, recommendation, and action-review UI

**Files:**
- Modify: `web/index.html`
- Modify: `web/app.js`
- Modify: `web/styles.css`
- Modify: `test_web_static.py`

**Interfaces:**
- Consumes: Task 1–4 APIs and WebSocket `approved_action` contract.
- Produces: Skillsets library section, attached-skill reason chips, session auto-attach controls, dismiss controls, action review cards, and typed destructive confirmation dialog.

- [ ] **Step 1: Add failing static-contract tests** for semantic Skillsets markup, attached-skill strip, visible reasons, auto-attach toggle, dismissal, safe text rendering, action Copy/Reject/Approve controls, exact destructive details, typed phrase, and no direct model command passed to `runTerminalCommand`.
- [ ] **Step 2: Run `python -m unittest -v test_web_static.py`** and verify the required elements/handlers are absent.
- [ ] **Step 3: Add accessible HTML/CSS** that remains readable in Light, Dark, and System themes and keeps large Skillsets collapsible.
- [ ] **Step 4: Implement generation-safe rendering and API calls** for Skillsets, previewed/attached recommendations, session exclusions, and automatic-attachment settings.
- [ ] **Step 5: Implement action review UI** that displays server-owned command/cwd/risk, obtains confirmation tokens, requires the typed destructive phrase, and sends only proposal ID/token through the guarded action channel.
- [ ] **Step 6: Run `python -m unittest -v test_web_static.py test_web_api.py test_actions.py`** and verify all tests pass.
- [ ] **Step 7: Commit** with `feat(web): add skillset routing and action approvals`.

### Task 6: V1.0.4 release, regression, publication, and live verification

**Files:**
- Create: `web_app/version.py`
- Modify: `web_app/app.py`
- Modify: `web/index.html`
- Modify: `run_web.ps1`
- Modify: `README.md` when the Word lock is released; otherwise document the locked-file exception without deleting `~$README.md`
- Modify: version assertions in `test_web_static.py` and related tests
- Modify: `docs/user/json-codr-skill-envelope.md` if action/Skillset usage affects the authoring contract

**Interfaces:**
- Consumes: completed Tasks 1–5.
- Produces: a tested, committed, pushed, GitHub-synchronized V1.0.4 application running at `http://127.0.0.1:8765/`.

- [ ] **Step 1: Add/update failing version tests** requiring canonical `APP_VERSION = "V1.0.4"`, `V1.0.4` from FastAPI metadata/health, settings `app_version`, header HTML, and launcher validation/output.
- [ ] **Step 2: Add `web_app/version.py`, expose the canonical value through application and settings responses, and update every authoritative version surface**; use `rg` to confirm no live V1.0.3 references remain outside historical design/plan documents.
- [ ] **Step 3: Update user documentation** for automatic Skillsets, reasons, prompt budgets, session exclusions, and both confirmation levels.
- [ ] **Step 4: Run focused suites** for models, settings, Skillsets, recommendations, context, actions, terminal, API, and static frontend; expect all pass.
- [ ] **Step 5: Run the complete suite** with `python -m unittest discover -v`, JavaScript syntax validation, PowerShell launcher validation, and `git diff --check`; expect zero unexpected failures.
- [ ] **Step 6: Request a fresh whole-branch code review**, fix actionable findings with focused regression tests, and repeat full verification.
- [ ] **Step 7: Stage only intended files, commit the release, and push the active `codex/` branch**; never stage `~$README.md`.
- [ ] **Step 8: Update the existing GitHub pull request** with the V1.0.4 feature and verification summary, then `git pull --ff-only` and verify local HEAD equals the pushed remote HEAD.
- [ ] **Step 9: Stop only the tracked JSON_CODR launcher/server processes, relaunch V1.0.4, and verify health, settings, 277-skill reconciliation, recommendation explanations, compressed attachment, normal approval, destructive second confirmation, and absence of NetSuite in the internal browser.
- [ ] **Step 10: Commit any verification-only fixes, push/re-sync again, and report final commit/PR/runtime evidence.**
