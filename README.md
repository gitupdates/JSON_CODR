# JSON_CODR

JSON_CODR V1.0.17-beta.1 is a localhost-only web and CLI interface for structured responses from local Ollama coding models.

V1.0.17-beta.1 adds an additive Continue CLI and Aider launcher to Live CLI. Each coding agent uses an explicit persistent full-authorization grant bound to one canonical project root and one tool. Direct Ollama chat remains the unconditional fallback when a coding CLI is missing, unconfigured, or fails to launch. Aider uses `ollama_chat/<model>` and Continue uses its local Ollama model slug; neither integration changes the Ollama service or active direct-chat model.

## Beta coding agents: Continue CLI and Aider

### Project Git broker

The **Git broker** is the compatible default execution profile. It gives native-tool models and models without Ollama tool support the same validated, project-scoped Git workflow. A persistent grant remains active across restarts until **Revoke** is selected. The broker inspects the current branch, refuses unexpected local changes, serializes model mutations, preserves the user's configured Git identity, records model attribution in commit trailers, synchronizes with the upstream branch, and pushes only after validation succeeds. Models such as Yi-Coder that reject native tool schemas are shown as using the **broker adapter** instead of exposing the provider's raw 400 response.

The **Unrestricted shell** profile is optional and non-sandboxed. Its project directory is the starting directory, not a filesystem security boundary. Continue and Aider remain separately authorized alternatives, and ordinary Chat continues to call Ollama directly when any coding profile is unavailable.

Open **Live CLI** from the global navigation. The **Beta coding agents** launcher appears above the existing PowerShell terminal; the original terminal remains available unchanged.

### Requirements and status

1. Keep Ollama running at `http://127.0.0.1:11434` and install the model you want to use.
2. Install at least one supported coding CLI and make it available on `PATH`:
   - Continue CLI: verify with `cn --version`.
   - Aider: verify with `aider --version`.
3. `GET /api/coding-agents/status` reports whether each executable is detected and lists saved grants. A missing CLI does not affect ordinary JSON_CODR chat.

### Start an interactive coding session

1. Select **Continue CLI** or **Aider**.
2. Select any installed Ollama model. Interactive mode permits every installed model, although smaller models may not reliably produce edits.
3. Enter the absolute root of the project the agent may inspect and edit.
4. Leave **Full persistent authorization** enabled to save an explicit grant for this project and this agent.
5. Select **Interactive**, then press **Launch agent**.
6. JSON_CODR opens the agent in the embedded terminal. Use the **PowerShell**, **Continue**, and **Aider** tabs to switch sessions without stopping them. Terminal output and keyboard input stay in the page, and a page reload reconnects to running sessions.

Continue launches with a generated local configuration that selects Ollama and the exact installed model. Aider launches with `aider --model ollama_chat/<model>` and receives `OLLAMA_API_BASE=http://127.0.0.1:11434` only in its child-process environment. On Windows, JSON_CODR uses ConPTY through pywinpty; the previous pipe or native-console launch remains a compatibility fallback when ConPTY is unavailable.

### Run a delegated task

1. Write the task in the main Chat prompt, including the intended files and expected outcome.
2. Open **Live CLI**, choose the tool, model, and project root, then select **Delegated**.
3. Press **Launch agent**. JSON_CODR sends the prompt to the chosen CLI only after a matching persistent grant exists.

Continue headless mode is limited to read, write, and edit tools and explicitly excludes shell execution. Aider runs with subtree-only editing, shell-command suggestions disabled, and automatic commits disabled. This authorization applies only to the canonical project root and selected tool; an Aider grant cannot authorize Continue, and another project needs its own grant.

The selected LLM can also return a structured `coding_agent_tasks` proposal. JSON_CODR displays that proposal in **Review actions**. Select **Review delegated task** to copy its tool, project boundary, and prompt into the launcher, then review the model, persistent authorization, and task before starting it. A model proposal never launches a process by itself.

### Authorization and safety boundaries

- Grants are stored locally in `%LOCALAPPDATA%\JSON_CODR\coding-agent-grants.json` using atomic replacement.
- A grant is bound to one canonical project root, one tool, and the `full` scope.
- Nested folders under that project are allowed. Missing projects, junctions/reparse points, and paths outside the approved root are rejected.
- Delegated agents may inspect and edit files inside the granted project but cannot run shell commands, install dependencies, create automatic commits, or publish remotely through this profile.
- Interactive sessions are user-operated CLIs embedded in JSON_CODR. JSON_CODR validates the project/tool grant before launch, but commands entered or approved inside the agent are governed by that CLI rather than JSON_CODR's PowerShell action-confirmation system.
- Disable a grant with `DELETE /api/coding-agents/grants/<grant-id>`. A settings-based grant manager is planned for a later beta.

### Direct Ollama fallback

The normal **Chat** page continues to call Ollama directly. It does not route through Continue or Aider. If either CLI is missing, its configuration is invalid, authorization is absent, or launch fails, return to Chat and run the selected local model normally. Coding-agent failures do not change the active model, Ollama hardware profile, skills, attachments, or benchmark data.

### Troubleshooting

- **`cn is not installed` / `aider is not installed`:** install the CLI, confirm its version in a new PowerShell session, and restart JSON_CODR so the updated `PATH` is inherited.
- **Persistent authorization required:** enable the authorization checkbox for the exact project/tool pair and launch again.
- **Invalid model name:** choose an installed model from the selector; manually injected shell characters are rejected.
- **Model runs but cannot edit reliably:** select a stronger coder model. Availability does not imply autonomous-editing capability.
- **Ollama connection error:** confirm `http://127.0.0.1:11434/api/tags` responds, then use normal Chat to verify the base model before retrying the coding agent.

## Skill catalog and settings

Open **Skills** to see active installed and saved skills. Each skill can be selected for the current chat, edited, enabled or disabled, reviewed through **Details**, and exported as provider-neutral Markdown documentation. Saving an enabled skill also applies it to the active session and opens the refreshed active-skill list.

Selected skills are sent to every supported local LLM using the same JSON_CODR skill schema. The schema supplies identity, intent, required capabilities, syntax guidance, execution direction, and the complete converted instructions. Provider-specific tool names remain capability requirements and do not bypass local authorization.

New skills can target JSON_CODR directly without provider conversion. Follow the [JSON_CODR Skill Envelope Standard](docs/user/json-codr-skill-envelope.md); its logical fields are also published as a [JSON Schema](docs/user/json-codr-skill-envelope.schema.json). Both files are downloadable from the Skills panel.

Use **Scan folder** to inspect an explicit local directory for Claude, Codex, generic skill folders, ZIP archives, and 7z archives. Discovery is preview-only until **Install** is selected. If an explicit scan finds nothing, JSON_CODR offers a separately confirmed scan of known provider locations. It never scans whole drives or installs skills silently.

Open **Settings** to control whether the Skills panel reopens at startup and to rescan or remove approved skill directories. Settings are stored under the configured JSON_CODR data root and are shared across local sessions.

## Hardware optimization and benchmarks

Open **Settings → Hardware optimization** to detect CPU, supported GPU runtimes, and Windows NPU or AI accelerator devices. CPU is the compatibility fallback. An accelerated Ollama backend is saved only after an isolated model-generation probe succeeds; unavailable NPU runtimes are reported without being executed.

V1.0.10 introduces LocalPerf minimum conformance for repeatable local-inference measurements. Quick runs execute the versioned 12-prompt LocalPerf-Core-v1 workload three times and Thorough runs seven times after warmup. Each configuration records generation throughput, streaming time-to-first-token, peak VRAM, quality checks, configuration identity, and atomic aggregate JSON plus sample JSONL artifacts. Incomplete or failed configurations remain visible but cannot be selected as conforming winners. Ollama CPU remains the compatibility fallback.

V1.0.16 adds capability-first holistic rankings and portable benchmark baseline exports that preserve the underlying integrity and performance evidence. V1.0.15 added strict versioned Integrity & Comprehension evaluations plus integrity-only and equal-weight quality/performance leaderboard rankings sourced only from persisted local benchmark evidence.

V1.0.11 added sanitized-by-default portable `.localperf.zip` reference packages with checksums, schemas, methodology, reporting templates, preview/import validation, and explicit consent for system details. Hardware Optimization reports model-specific acceleration states and provides a pinned offline optimized-model catalog plus explicit on-demand search of approved remote model metadata. A model is labeled accelerated only after model-specific evidence or a successful provider probe.

The **Benchmarks** tab compares CPU with all detected runnable backends or one selected optimization using the same model and LocalPerf-Core-v1 workload. A selected accelerator is always paired with a fresh CPU baseline. **Quick** runs 12 prompts three times; **Thorough** runs them seven times after warmup. Results show conformance, model/runtime verification, TTFT, peak VRAM, duration, quality, token throughput, and CPU-relative performance. Benchmarking does not change the active backend, and canonical runs are stored under the JSON_CODR data root.

## Requirements

- Windows with Python 3.8 or newer
- Ollama available in `PATH`
- At least one configured model installed in Ollama

Install Python dependencies:

```powershell
python -m pip install -r requirements.txt
```

## Run the web interface

```powershell
.\run_web.ps1
```

The launcher starts Ollama when necessary, serves the application at
`http://127.0.0.1:8765`, and opens the page in your default browser. Press
Ctrl+C in the launcher window to stop the web server.

If your Ollama models use a custom directory, set it before launching:

```powershell
$env:JSON_CODR_MODELS = 'D:\path\to\ollama-models'
.\run_web.ps1
```

The server binds only to `127.0.0.1`; it is not exposed to other machines.

## Run tests

```powershell
python -m unittest discover -v
```
JSON_CODR
