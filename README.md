# JSON_CODR

JSON_CODR V1.0.0 is a localhost-only web and CLI interface for structured responses from local Ollama coding models.

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
