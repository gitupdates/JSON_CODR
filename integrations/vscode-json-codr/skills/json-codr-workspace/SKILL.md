---
name: json-codr-workspace
description: Submit coding work to a running local JSON_CODR BORG workspace and track its real result.
---

1. Verify the local service with `json_codr.health`.
2. Obtain the JSON_CODR session ID, project root, requested outcome, and model selection. Use `auto` when no model was requested.
3. Call `json_codr.run_workspace_task` once with those values.
4. Preserve the returned task ID, route, effective model, warnings, and status.
5. If the status is `approval_required`, tell the user which task is waiting. If it is `running`, report it as running. Claim completion only when the returned durable task state is completed.
