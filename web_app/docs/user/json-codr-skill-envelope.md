# JSON_CODR Skill Envelope Standard

Version 1 defines a provider-neutral Markdown format for skills that work with any LLM selected in JSON_CODR. A conforming native skill is preserved as written and does not require Claude-, Codex-, or other provider conversion.

## Package layout

Place each skill in its own directory with an entry file named `SKILL.md`. Distribute one or more skill directories in a ZIP or 7z archive.

```text
review-code/
  SKILL.md
```

Archives may contain at most 200 files and 10 MiB of uncompressed data. Archive paths must be relative and must not contain `..` segments.

## Required structure

`SKILL.md` is UTF-8 Markdown with three ordered parts: YAML discovery metadata, the JSON_CODR envelope, and instructions inside the boundary markers.

```markdown
---
name: review-code
description: Review source code for correctness, security, and maintainability.
---
--- JSON_CODR SKILL ENVELOPE ---
JSON_CODR_SKILL_SCHEMA: 1
NAME: review-code
INTENT: Review supplied source code and report actionable findings.
CAPABILITIES: read, search
SYNTAX: Select this skill and provide {{arguments}} as the review request.
EXECUTION_DIRECTIVE: Follow the instructions in order using authorized capabilities only. Report unavailable requirements honestly.
--- BEGIN CONVERTED SKILL ---
Inspect the supplied code and context.
Prioritize correctness and security defects.
Return findings with file locations and concrete remediation.
--- END CONVERTED SKILL ---
```

The exact line `JSON_CODR_SKILL_SCHEMA: 1` identifies a native envelope. JSON_CODR preserves content containing this marker instead of applying provider conversion.

## Field schema

| Field | Requirement | Syntax and meaning |
| --- | --- | --- |
| `name` | Required YAML metadata | Lowercase letters, digits, and hyphens; at most 64 characters. It is the discovery name and stable ID source. |
| `description` | Required YAML metadata | One concise sentence describing the skill and when to select it. |
| `JSON_CODR_SKILL_SCHEMA` | Required | Integer `1`. Other versions are not defined by this standard. |
| `NAME` | Required | Must equal YAML `name`; gives every selected LLM an explicit skill identity. |
| `INTENT` | Required | State the desired outcome, not implementation history. |
| `CAPABILITIES` | Required | Comma-separated requirements such as `read`, `write`, `search`, `web`, or `cli`. These are not permission grants. |
| `SYNTAX` | Required | Explain how input maps into the skill. Use `{{arguments}}` for the current user request. |
| `EXECUTION_DIRECTIVE` | Required | Direct the LLM to apply the instructions while obeying capability authorization. |
| Converted-skill block | Required | Markdown instructions between the exact begin and end markers. |

The machine-readable logical-field definition is [`json-codr-skill-envelope.schema.json`](json-codr-skill-envelope.schema.json). The JSON Schema describes the logical fields; the installed transport remains the line-oriented `SKILL.md` format.

Unknown envelope fields may be added after `EXECUTION_DIRECTIVE`. Readers must ignore fields they do not understand. Authors must not redefine standard fields.

## Authorization rules

`CAPABILITIES` declares what a skill may need. It never installs software, enables tools, or authorizes commands.

- Use only capabilities available to the selected LLM and current session.
- Ask the user before running CLI commands or installing prerequisites.
- Do not silently substitute a similarly named tool.
- Report unavailable capabilities and resulting limitations.
- Never claim an action completed unless its result was observed.

Prefer portable names such as `read, search, write` over provider tool names such as `Read, Glob, Grep, Write`.

## Instruction syntax

Write direct Markdown instructions. Use imperative steps when order matters and explicit conditions when behavior branches. Keep provider APIs out of the body unless the skill is intentionally provider-specific.

`{{arguments}}` represents the user's current request:

```markdown
Interpret {{arguments}} as the review goal and scope.
If no file is attached, ask the user for the material to review.
```

Describe the desired operation without assuming a capability exists. JSON_CODR exposes only the capabilities actually available in the session.

## Conformance requirements

A version-1 skill is compatible without conversion when:

- The archive contains a UTF-8 `SKILL.md`.
- YAML metadata contains lowercase `name:` and `description:` keys.
- The native marker is exactly `JSON_CODR_SKILL_SCHEMA: 1`.
- All six envelope fields are present and single-line.
- `NAME` matches `name`.
- The exact instruction boundary markers occur once and in order.
- Instructions do not require silent privilege escalation or unapproved installation.
- Required resources are included or identified as explicit prerequisites.

## Write and install a native skill

1. Create a lowercase hyphenated directory containing `SKILL.md`.
2. Copy the required structure and replace every field and instruction.
3. Save as UTF-8 and compress the directory as ZIP or 7z.
4. Import the archive and select **Review as skills**.
5. Verify the preview, then install the reviewed pack.
6. Enable and save the skill for the active session.

Native skills may also be found with **Scan folder**. Scanning is preview-only; installation remains a separate user action.

## Common incompatibilities

- Missing lowercase YAML `name:` makes JSON_CODR derive a name from the directory.
- Missing the exact schema marker makes the file eligible for provider conversion.
- `$ARGUMENTS` is provider-specific; use `{{arguments}}`.
- A CLI or package listed in `CAPABILITIES` is not automatically installed.
- Instructions outside the boundary markers have ambiguous execution scope.
- Secrets, credentials, and machine-specific absolute paths make skills unsafe and non-portable.
