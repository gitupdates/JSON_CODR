param(
  [switch]$NoBrowser,
  [switch]$ValidateOnly,
  [switch]$Direct
)

$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$HostAddress = '127.0.0.1'
$Port = 8765
$Url = "http://${HostAddress}:$Port"
$Version = 'V1.3.7'
$PythonCandidates = @()
if ($env:JSON_CODR_PYTHON) {
  $PythonCandidates += $env:JSON_CODR_PYTHON
}
$KnownPython314 = Join-Path $env:LOCALAPPDATA 'Programs\Python\Python314\python.exe'
$KnownPython315 = Join-Path $env:LOCALAPPDATA 'Python\bin\python3.15.exe'
if (Test-Path -LiteralPath $KnownPython314) { $PythonCandidates += $KnownPython314 }
if (Test-Path -LiteralPath $KnownPython315) { $PythonCandidates += $KnownPython315 }
$PythonCandidates += @('python3.14', 'python3.15', 'python')

$Python = $null
$SeenPythonPaths = @{}
foreach ($Candidate in $PythonCandidates) {
  $PythonCommand = Get-Command $Candidate -ErrorAction SilentlyContinue
  if (-not $PythonCommand) { continue }
  foreach ($Command in @($PythonCommand)) {
    $PythonPath = $Command.Source
    if (-not $PythonPath -or $SeenPythonPaths.ContainsKey($PythonPath)) { continue }
    $SeenPythonPaths[$PythonPath] = $true
    & $PythonPath -c "from uuid import uuid7; import fastapi, uvicorn, pydantic, ollama" *> $null
    if ($LASTEXITCODE -eq 0) {
      $Python = $PythonPath
      break
    }
  }
  if ($Python) { break }
}
if (-not $Python) {
  throw 'A compatible Python 3.14 or newer interpreter is required.'
}
$CompatiblePythonCandidates = @()
if ($env:JSON_CODR_COMPATIBLE_PYTHON) {
  $CompatiblePythonCandidates += $env:JSON_CODR_COMPATIBLE_PYTHON
}
$KnownPython312 = Join-Path $env:LOCALAPPDATA 'Programs\Python\Python312\python.exe'
$KnownPython311 = Join-Path $env:LOCALAPPDATA 'Programs\Python\Python311\python.exe'
if (Test-Path -LiteralPath $KnownPython312) { $CompatiblePythonCandidates += $KnownPython312 }
if (Test-Path -LiteralPath $KnownPython311) { $CompatiblePythonCandidates += $KnownPython311 }
$CompatiblePythonCandidates += @('python3.12', 'python3.11', 'python')
$CompatiblePython = $null
$SeenCompatiblePythonPaths = @{}
foreach ($Candidate in $CompatiblePythonCandidates) {
  $PythonCommand = Get-Command $Candidate -ErrorAction SilentlyContinue
  if (-not $PythonCommand) { continue }
  foreach ($Command in @($PythonCommand)) {
    $PythonPath = $Command.Source
    if (-not $PythonPath -or $SeenCompatiblePythonPaths.ContainsKey($PythonPath)) { continue }
    $SeenCompatiblePythonPaths[$PythonPath] = $true
    $VersionOutput = & $PythonPath -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>$null
    if ($LASTEXITCODE -eq 0 -and $VersionOutput -in @('3.11', '3.12')) {
      $CompatiblePython = $PythonPath
      break
    }
  }
  if ($CompatiblePython) { break }
}
if (-not $CompatiblePython) {
  throw 'A Python 3.11 or 3.12 interpreter is required for optional provider environments.'
}
$OllamaCommand = Get-Command ollama -ErrorAction SilentlyContinue
if ($OllamaCommand) {
  $Ollama = $OllamaCommand.Source
} else {
  $Ollama = Join-Path $env:LOCALAPPDATA 'Programs\Ollama\ollama.exe'
  if (-not (Test-Path -LiteralPath $Ollama)) {
    throw 'Ollama is not installed or available in PATH.'
  }
}

if ($ValidateOnly) {
  [pscustomobject]@{
    host = $HostAddress
    port = $Port
    url = $Url
    version = $Version
    python = $Python
    compatiblePython = $CompatiblePython
    ollama = $Ollama
    modelStore = $env:JSON_CODR_MODELS
    supervised = -not $Direct
    ollamaNoCloud = $true
  } | ConvertTo-Json
  exit 0
}

$env:PYTHONUTF8 = '1'
$env:PYTHONIOENCODING = 'utf-8'
$env:OLLAMA_NO_CLOUD = '1'
$env:JSON_CODR_COMPATIBLE_PYTHON = $CompatiblePython
if ($env:JSON_CODR_MODELS) {
  $env:OLLAMA_MODELS = $env:JSON_CODR_MODELS
}
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

$OwnedOllama = $null
$WebProcess = $null
try {
  try {
    Invoke-RestMethod -Uri 'http://127.0.0.1:11434/api/tags' -TimeoutSec 2 | Out-Null
  } catch {
    $OwnedOllama = Start-Process -FilePath $Ollama -ArgumentList 'serve' -WindowStyle Hidden -PassThru
    for ($Attempt = 0; $Attempt -lt 30; $Attempt++) {
      Start-Sleep -Milliseconds 500
      try {
        Invoke-RestMethod -Uri 'http://127.0.0.1:11434/api/tags' -TimeoutSec 2 | Out-Null
        break
      } catch {
        if ($Attempt -eq 29) { throw 'Ollama did not become ready.' }
      }
    }
  }

  if ($Direct) {
    $WebArguments = @('-m', 'uvicorn', 'web_app.app:app', '--host', $HostAddress, '--port', $Port)
  } else {
    $WebArguments = @('supervisor.py', '--host', $HostAddress, '--port', $Port)
  }
  $WebProcess = Start-Process -FilePath $Python -ArgumentList $WebArguments -WorkingDirectory $Root -WindowStyle Hidden -PassThru

  for ($Attempt = 0; $Attempt -lt 30; $Attempt++) {
    Start-Sleep -Milliseconds 300
    try {
      Invoke-RestMethod -Uri "$Url/api/health" -TimeoutSec 2 | Out-Null
      break
    } catch {
      if ($WebProcess.HasExited) { throw "Web server exited with code $($WebProcess.ExitCode)." }
      if ($Attempt -eq 29) { throw 'Web server did not become ready.' }
    }
  }

  Write-Host "JSON_CODR $Version is running at $Url"
  Write-Host 'Press Ctrl+C to stop the local web server.'
  if (-not $NoBrowser) { Start-Process $Url }
  Wait-Process -Id $WebProcess.Id
} finally {
  if ($WebProcess -and -not $WebProcess.HasExited) {
    & taskkill.exe /PID $WebProcess.Id /T /F *> $null
  }
  if ($OwnedOllama -and -not $OwnedOllama.HasExited) {
    Stop-Process -Id $OwnedOllama.Id -Force
  }
}
