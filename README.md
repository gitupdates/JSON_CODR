# JSON_CODR

JSON_CODR V1.0.1 is a localhost-only web and CLI interface for structured responses from local Ollama coding models.

## Skill catalog and settings

Open **Skills** to see active installed and saved skills. Each skill can be selected for the current chat, edited, enabled or disabled, reviewed through **Details**, and exported as provider-neutral Markdown documentation. Saving an enabled skill also applies it to the active session and opens the refreshed active-skill list.

Selected skills are sent to every supported local LLM using the same JSON_CODR skill schema. The schema supplies identity, intent, required capabilities, syntax guidance, execution direction, and the complete converted instructions. Provider-specific tool names remain capability requirements and do not bypass local authorization.

New skills can target JSON_CODR directly without provider conversion. Follow the [JSON_CODR Skill Envelope Standard](docs/user/json-codr-skill-envelope.md); its logical fields are also published as a [JSON Schema](docs/user/json-codr-skill-envelope.schema.json). Both files are downloadable from the Skills panel.

Use **Scan folder** to inspect an explicit local directory for Claude, Codex, generic skill folders, ZIP archives, and 7z archives. Discovery is preview-only until **Install** is selected. If an explicit scan finds nothing, JSON_CODR offers a separately confirmed scan of known provider locations. It never scans whole drives or installs skills silently.

Open **Settings** to control whether the Skills panel reopens at startup and to rescan or remove approved skill directories. Settings are stored under the configured JSON_CODR data root and are shared across local sessions.

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
