# Automatic Skillsets and Confirmed Actions Design

## Intent

JSON_CODR should turn a large installed skill library into useful, explainable capability without requiring the user to manually search hundreds of skills. For each request, the application will recommend and attach a small set of relevant skills, combine related skills into reference-based Skillset packs, compress repeated documentation, and require an explicit user confirmation before any skill-originated terminal command runs.

## Goals

- Recommend relevant skills from the installed library using deterministic, local rules.
- Automatically attach the accepted recommendations to the current request.
- Explain every recommendation in plain language, including the matching prompt terms, attachment types, or declared capabilities.
- Group related skills into stable Skillset packs without copying their full source content.
- Compress repeated envelopes, safety language, and overlapping documentation before sending context to the model.
- Keep the context bounded so large libraries cannot overwhelm small local models.
- Turn terminal-capable skill output into reviewable action proposals that require a one-shot confirmation.
- Preserve manual skill selection and allow the user to disable an automatic recommendation for a session.

## Non-goals

- No autonomous shell execution from model text or imported skill instructions.
- No model-based router in the first release.
- No semantic embedding service, cloud API, or new external dependency.
- No rewriting of the original installed skill documents.
- No automatic installation of software requested by an imported skill. Existing prerequisite handling remains a separate trusted application workflow.
- No attempt to apply every enabled skill to every request.

## Anti-goals

- A recommendation must not be opaque: the UI must show why it matched.
- Imported documentation must not be treated as authority to execute a command.
- Skillsets must not duplicate member content or create conflicting copies of a skill.
- A broad category match must not consume most of the prompt budget.
- A terminal approval must not authorize a different command, working directory, or later request.

## Current constraints

- Installed skills are stored as `SkillPack` records and are attached only through `SessionRecord.selected_skill_ids`.
- `ContextAssembler` currently repeats a full envelope for every selected skill and has a 20,000-character attachment budget.
- The active local model may be as small as `qwen2.5-coder:0.5b`, so routing cannot depend on strong model judgment.
- The imported library currently contains 277 enabled skills; 168 describe potentially mutating actions and 73 contain provider-specific references.
- The terminal is an interactive PowerShell session exposed through a guarded API and WebSocket.

## Approaches considered

### 1. Deterministic rules-first router — selected

Build a local index from names, descriptions, declared capabilities, normalized headings, and file-type hints. Score prompt and attachment signals, choose the best Skillsets, then choose the strongest member skills within a fixed budget.

This is predictable, fast, testable, and works with the smallest supported model. Its tradeoff is that synonyms and subtle intent require maintained routing vocabulary.

### 2. Local-model router

Ask the active Ollama model to choose skills. This may understand nuanced language better, but it adds latency and produces inconsistent choices with very small models. It also makes routing harder to explain and test.

### 3. Hybrid rules plus model reranking

Use deterministic rules for a shortlist and a local model for final ranking. This can improve semantic matching, but it adds significant complexity and still depends on model quality. The rules-first design will expose a ranking boundary so optional reranking can be added later.

## Data model

Add a reference-based `SkillsetRecord` with:

- stable `id`, display `name`, and `category`;
- member references in `pack_id:skill_id` form;
- normalized routing terms and attachment extensions;
- a short generated summary;
- `enabled` and `auto_attach` flags;
- a version field for future migration.

Skillsets are stored under the JSON_CODR data root in `skillsets.json`. They reference the canonical library records; member instructions are never copied into this file. Reconciliation removes missing references and refreshes generated sets after library installation, removal, deduplication, or skill edits.

The first generated categories are Coding, Testing and Review, Browser and UI, Documents, Data and AI, Cloud and Delivery, Security, Planning, and Integrations. A skill may belong to more than one set, but the router attaches each underlying skill at most once.

## Routing and recommendation

`SkillRecommendationService` builds a normalized index from enabled skills and Skillsets. It receives the user prompt plus attachment metadata, never attachment instructions, and calculates:

- exact and stemmed term matches;
- declared-capability matches;
- attachment extension and detected-type matches;
- category affinity;
- penalties for generic terms, missing descriptions, and provider-only instructions.

The service returns ranked recommendations with scores and human-readable reasons. Defaults:

- no more than three Skillsets;
- no more than five distinct skills;
- a minimum score before automatic attachment;
- no more than 12,000 characters of skill context;
- stable tie-breaking by pack and skill ID.

Manual session selections remain authoritative and are included first. Automatically chosen skills fill the remaining budget. A session-level exclusion prevents a dismissed recommendation from immediately returning.

## Skill context compression

`ContextAssembler` will render one shared JSON_CODR safety and execution header, followed by a compact Skillset summary and the unique instruction body for each chosen member. It will remove duplicated JSON_CODR envelopes, repeated compatibility paragraphs, and identical capability lines during rendering without altering stored originals.

The assembled prompt records which skills were manual and which were automatically attached. Truncation happens at skill boundaries; JSON_CODR will not cut an instruction in the middle. Attachment context keeps a separate bounded allocation so skill recommendations cannot starve attached source files.

## User experience

The Skills panel gains a Skillsets section showing generated packs, member counts, enabled state, and a concise combined description. The chat workspace gains an `Attached skills` strip that shows:

- manual selections;
- automatically recommended Skillsets and skills;
- a short reason for each automatic match;
- controls to dismiss a recommendation or disable automatic attachment for the session.

The backend remains authoritative: sending a chat request recalculates recommendations so a stale or manipulated browser state cannot attach missing, disabled, or deleted skills.

## Confirmed terminal actions

Skill-originated commands are represented as `ActionProposal` records containing the exact command, working directory, explanation, source skill references, risk classification, and a short-lived one-shot confirmation token.

The Ollama response uses an explicit structured `actions` field to suggest a command. Arbitrary prose and fenced code blocks are never parsed into actions. The server validates every structured proposal before storing it; suggestion text alone cannot reach the terminal. JSON_CODR displays proposed commands in a review area with `Copy`, `Reject`, and `Approve and run`. Approval binds to the exact command and working directory. Any change invalidates the token. The terminal API continues to require its existing JSON_CODR header, and it additionally requires the valid proposal token for a skill-originated action. The ordinary terminal input remains a direct, user-initiated path and does not accept model-originated commands.

Normal skill-originated commands require one explicit approval. Commands with destructive patterns require a second, stronger confirmation that repeats the exact command, working directory, and risk explanation and asks the user to type a displayed confirmation phrase. The second confirmation issues a separate 60-second, one-shot execution token. Unknown commands are classified as destructive. No approval survives a server restart, crosses chat sessions, or can be consumed by a different terminal. Non-destructive proposal tokens expire after five minutes. Rejecting, editing, consuming, or superseding a proposal invalidates all of its tokens.

Action proposals are held in memory and scoped to the chat session. They do not survive a restart. A terminal ID is bound when the final approval is granted. Existing dependency installation remains a separate trusted workflow and is not authorized by imported skill content.

## Initial routing policy

Routing uses lowercase Unicode-normalized tokens, splits punctuation and common identifier separators, and applies a conservative suffix stemmer for `s`, `es`, `ed`, and `ing` only when the remaining token has at least four characters. The first-release score is deterministic:

- exact prompt term in skill name: 8;
- exact prompt term in declared capability: 6;
- exact prompt term in description: 4;
- stemmed or routing-synonym match: 2;
- attachment extension or detected-type match: 8;
- Skillset category match: 3;
- generic-term-only match: minus 4;
- missing description: minus 2;
- provider-only instruction with no available matching capability: minus 6.

A skill needs a score of at least 8 for automatic attachment. Tests will use a checked-in routing vocabulary and representative prompts; tuning changes require fixture updates so behavior never shifts silently.

## Reconciliation and user-owned fields

Generated Skillsets own category, generated membership, routing terms, attachment hints, and generated summaries. Reconciliation refreshes those fields. User-owned `enabled` and `auto_attach` choices persist by stable Skillset ID. The first release does not support manual membership edits or renaming generated Skillsets; user-created custom Skillsets are deferred so reconciliation cannot overwrite user-authored structure.

## Prompt budgets

The assembled non-user context has a 20,000-character ceiling. Skill context may use at most 12,000 characters, attachment reference data is guaranteed at least 8,000 characters when attachments are present, and either side may borrow unused capacity from the other. Manual skills have priority over automatic skills, but no skill instruction is cut mid-document. The original user request is outside this context allocation and is always preserved in full.

## API changes

- `GET /api/skillsets` lists reconciled Skillset packs.
- `POST /api/sessions/{session_id}/skill-recommendations` previews recommendations for a prompt and current attachments.
- Chat results include the attached skill references, Skillsets, and recommendation reasons.
- Session updates support recommendation exclusions and automatic-attachment enablement.
- Action-proposal endpoints create, approve, reject, and consume one-shot terminal confirmations.

Existing skill-pack and manual-selection endpoints remain compatible.

## Failure behavior

- Router failure falls back to manual selections only.
- Missing or disabled members are skipped during reconciliation and prompt assembly.
- If no recommendation crosses the threshold, no automatic skill is attached.
- If the context budget is exhausted, lower-ranked skills are omitted and the UI reports that limit.
- An expired, reused, altered, or mismatched action token fails closed without terminal execution.

## Testing

- Unit tests for categorization, scoring, stable ordering, thresholds, exclusions, and attachment-type signals.
- Unit tests proving reference-based Skillsets do not duplicate stored instructions.
- Context tests for envelope deduplication, whole-skill truncation, separate budgets, and manual-selection priority.
- API tests for recommendation previews, chat metadata, reconciliation, and stale references.
- Security tests proving model text cannot directly invoke the terminal and confirmation tokens are exact, one-shot, and expiring.
- Frontend tests for visible reasons, dismissal, session toggle, Skillset details, and confirmed action controls.
- Regression tests for existing manual skills, attachments, dependency preflight, and terminal behavior.

## Delivery shape

Implement in three vertical slices: reference-based Skillsets and reconciliation; deterministic recommendation plus compressed prompt attachment; then confirmed terminal action proposals. Each slice remains usable and testable on its own, with no cloud dependency.

The completed release is version `V1.0.4`. A canonical application-version constant drives API and settings responses; user-visible labels, settings schema migration, launch messages, documentation, and health metadata are updated together. The change is tested locally, committed and pushed to the active GitHub branch, the open pull request is updated, the branch is re-synchronized from GitHub, and the local application is relaunched and verified in the internal browser.
