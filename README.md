# JSON_CODR

JSON_CODR V1.0.18-alpha.8 is a localhost-only, unified project agent for local Ollama models.

## Unified project workflow

Choose a model, describe the outcome in **Chat**, and run it. JSON_CODR creates one durable task for the conversation and routes all model, project, terminal, Git, browser, skill, and optional-provider work through that task. Users do not select an internal executor.

The response panel shows live activity and the requested and effective model identities. Use **Steer** by entering more direction while a task is active, **Stop** to request cancellation, **Retry** to create a linked retry, and **Undo** when the task produced a checkpoint. Execution details stay collapsed until needed. The **Live CLI** is the terminal view of the same local system, with command history, clipboard support, resize/reconnect, and the Ctrl+X then Ctrl+C interrupt chord.

V1.0.18-alpha.8 turns Live CLI into a provider-neutral **Project Workspace**. **Shell** retains the interactive ConPTY PowerShell session. **Agent** accepts a project root, installed local model, and coding outcome, then runs the schema-constrained Git broker through CoreService and displays the requested model, effective model, route, and verified action result. It does not require or impersonate Codex, Continue, or Aider.

Local reads, searches, tests, bounded edits, and inference can run automatically inside the selected project boundary. Network access, installation, Git publication, destructive changes, and budget overrides require policy approval. Persistent grants remain project-scoped and can be revoked. A model without native tool calling may use a verified brokered route; JSON_CODR always displays the requested and effective model and never labels that route as native.

Attachments and folders can be selected or dropped into the page. Skills, MCP resources, browser automation, REA/Ghidra analysis, language intelligence, schedules, hooks, and child tasks use the same capability and policy path. Imported components are staged, probed, provenance-recorded, and either activated or quarantined. Optional provider failure leaves the base Ollama/CPU path available.

Remote PyPI and npm components require exact coordinates such as `cowsay==6.1` or `cowsay@1.6.0`. Before approval, BORG displays extracted identity, dependencies, hashes, entry points, blocked build behavior, and every required compatibility alteration. Installation preserves the acquired package, records observed native launchers separately from effective normalized commands, and activates only after a real probe succeeds. Local, Git, and archive sources cannot claim trusted registry provenance merely by including manifest filenames.

### Headless use

Submit through the neutral task API or CLI:

```powershell
python -m web_app.core.cli run --project D:\path\to\project --output text "Inspect, edit, and test this project"
```

`json`, `text`, and `stream-json` outputs are supported. Exit code `0` means completed, `1` means failed, and `2` means permission is required.

### Migrating beta data

The alpha migration is copy-on-write: the beta data root is hashed and never modified. General settings, project permissions, skills, benchmark history, imported resources, and valid conversations are copied; secrets are excluded. Older executor-specific configuration is archived as inactive evidence. Malformed records are reported, and the new destination can be rolled back without touching the source.

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
