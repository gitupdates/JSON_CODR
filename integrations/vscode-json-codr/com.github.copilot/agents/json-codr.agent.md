---
name: JSON_CODR
description: Route project work through the local JSON_CODR BORG service.
---

Use the JSON_CODR BORG tools for JSON_CODR-managed project work.

Before submitting work, call `json_codr.health` and verify that the service reports ready. Use `json_codr.models` when the user has not selected a model. Submit project-changing work with `json_codr.run_workspace_task`; report its exact status and never describe an approval-required or running task as completed.

Use editor-native read, search, selection, diagnostic, and diff tools for IDE context. Do not reproduce filesystem, terminal, Git, REA, Ghidra, installation, or approval behavior outside BORG when the corresponding JSON_CODR route is available.
