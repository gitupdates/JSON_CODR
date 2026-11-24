param(
  [switch]$NoBrowser,
  [switch]$ValidateOnly,
  [switch]$Direct
)

$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$RuntimeConfigPath = Join-Path $Root 'config\runtime.json'
if (-not (Test-Path -LiteralPath $RuntimeConfigPath)) {
  throw "Runtime configuration is missing: $RuntimeConfigPath"
}
try {
  $Runtime = Get-Content -LiteralPath $RuntimeConfigPath -Raw | ConvertFrom-Json
} catch {
  throw "Runtime configuration is invalid: $RuntimeConfigPath"
}
$RequiredRuntimeProperties = @('schema_version', 'version', 'host', 'port', 'api_paths', 'python', 'default_roots', 'allowed_environment_overrides')
foreach ($PropertyName in $RequiredRuntimeProperties) {
  if ($null -eq $Runtime.$PropertyName) { throw "Runtime configuration is missing '$PropertyName'." }
}
foreach ($PropertyName in @('health', 'runtime_status', 'tasks')) {
  if ([string]::IsNullOrWhiteSpace($Runtime.api_paths.$PropertyName)) {
    throw "Runtime configuration is missing API path '$PropertyName'."
  }
}
foreach ($PropertyName in @('host_versions', 'compatible_versions')) {
  if ($null -eq $Runtime.python.$PropertyName -or @($Runtime.python.$PropertyName).Count -eq 0) {
    throw "Runtime configuration is missing Python versions '$PropertyName'."
  }
}
foreach ($PropertyName in @('data_root_segment', 'launcher_root_segment')) {
  if ([string]::IsNullOrWhiteSpace($Runtime.default_roots.$PropertyName)) {
    throw "Runtime configuration is missing default root '$PropertyName'."
  }
}
$HostAddress = [string]$Runtime.host
$Port = [int]$Runtime.port
$Url = "http://${HostAddress}:$Port"
$Version = [string]$Runtime.version
$DataRoot = if ($env:JSON_CODR_DATA_ROOT) { $env:JSON_CODR_DATA_ROOT } else { Join-Path $env:LOCALAPPDATA ([string]$Runtime.default_roots.data_root_segment) }
$LauncherStateRoot = if ($env:JSON_CODR_LAUNCHER_ROOT) { $env:JSON_CODR_LAUNCHER_ROOT } else { Join-Path $DataRoot ([string]$Runtime.default_roots.launcher_root_segment) }
$ActiveBuildPointer = Join-Path $LauncherStateRoot 'pointer\active-build.json'
$PythonCandidates = @()
if ($env:JSON_CODR_PYTHON) {
  $PythonCandidates += $env:JSON_CODR_PYTHON
}
foreach ($PythonVersion in @($Runtime.python.host_versions)) {
  $CompactVersion = ([string]$PythonVersion).Replace('.', '')
  $PythonCandidates += Join-Path $env:LOCALAPPDATA "Programs\Python\Python$CompactVersion\python.exe"
  $PythonCandidates += Join-Path $env:LOCALAPPDATA "Python\bin\python$PythonVersion.exe"
  $PythonCandidates += "python$PythonVersion"
}
$PythonCandidates += 'python'

$Python = $null
$SeenPythonPaths = @{}
foreach ($Candidate in $PythonCandidates) {
  $PythonCommand = Get-Command $Candidate -ErrorAction SilentlyContinue
  if (-not $PythonCommand) { continue }
  foreach ($Command in @($PythonCommand)) {
    $PythonPath = $Command.Source
    if (-not $PythonPath -or $SeenPythonPaths.ContainsKey($PythonPath)) { continue }
    $SeenPythonPaths[$PythonPath] = $true
    $CandidateErrorActionPreference = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    & $PythonPath -c "from uuid import uuid7; import fastapi, uvicorn, pydantic, ollama" *> $null
    $ErrorActionPreference = $CandidateErrorActionPreference
    if ($LASTEXITCODE -eq 0) {
      $Python = $PythonPath
      break
    }
  }
  if ($Python) { break }
}
if (-not $Python) { throw "A compatible Python $($Runtime.python.host_versions -join ' or ') interpreter is required." }
$CompatiblePythonCandidates = @()
if ($env:JSON_CODR_COMPATIBLE_PYTHON) {
  $CompatiblePythonCandidates += $env:JSON_CODR_COMPATIBLE_PYTHON
}
foreach ($PythonVersion in @($Runtime.python.compatible_versions)) {
  $CompactVersion = ([string]$PythonVersion).Replace('.', '')
  $CompatiblePythonCandidates += Join-Path $env:LOCALAPPDATA "Programs\Python\Python$CompactVersion\python.exe"
  $CompatiblePythonCandidates += "python$PythonVersion"
}
$CompatiblePythonCandidates += 'python'
$CompatiblePython = $null
$SeenCompatiblePythonPaths = @{}
foreach ($Candidate in $CompatiblePythonCandidates) {
  $PythonCommand = Get-Command $Candidate -ErrorAction SilentlyContinue
  if (-not $PythonCommand) { continue }
  foreach ($Command in @($PythonCommand)) {
    $PythonPath = $Command.Source
    if (-not $PythonPath -or $SeenCompatiblePythonPaths.ContainsKey($PythonPath)) { continue }
    $SeenCompatiblePythonPaths[$PythonPath] = $true
    $CandidateErrorActionPreference = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    $VersionOutput = & $PythonPath -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>$null
    $ErrorActionPreference = $CandidateErrorActionPreference
    if ($LASTEXITCODE -eq 0 -and $VersionOutput -in @($Runtime.python.compatible_versions)) {
      $CompatiblePython = $PythonPath
      break
    }
  }
  if ($CompatiblePython) { break }
}
if (-not $CompatiblePython) { throw "A Python $($Runtime.python.compatible_versions -join ' or ') interpreter is required for optional provider environments." }
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
    healthPath = [string]$Runtime.api_paths.health
    runtimeStatusPath = [string]$Runtime.api_paths.runtime_status
    python = $Python
    compatiblePython = $CompatiblePython
    ollama = $Ollama
    modelStore = $env:JSON_CODR_MODELS
    dataRoot = $DataRoot
    supervised = -not $Direct
    ollamaNoCloud = $true
    stableLauncher = -not $Direct
    activeBuildPointer = $ActiveBuildPointer
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
    $Revision = if ($env:JSON_CODR_REVISION) { $env:JSON_CODR_REVISION } else { (& git -C $Root rev-parse HEAD 2>$null) }
    if (-not $Revision) { $Revision = 'development' }
    $WebArguments = @(
      'json_codr_launcher.py', '--pointer', $ActiveBuildPointer,
      '--fallback-root', $Root, '--fallback-revision', $Revision,
      '--fallback-version', $Version, '--python', $Python,
      '--host', $HostAddress, '--port', $Port, '--data-root', $DataRoot
    )
  }
  $WebProcess = Start-Process -FilePath $Python -ArgumentList $WebArguments -WorkingDirectory $Root -WindowStyle Hidden -PassThru

  for ($Attempt = 0; $Attempt -lt 30; $Attempt++) {
    Start-Sleep -Milliseconds 300
    try {
      Invoke-RestMethod -Uri "$Url$($Runtime.api_paths.health)" -TimeoutSec 2 | Out-Null
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
    if (-not $Direct) {
      try {
        & $Python @WebArguments --request-shutdown *> $null
        Wait-Process -Id $WebProcess.Id -Timeout 10 -ErrorAction SilentlyContinue
      } catch {
        # The bounded taskkill fallback below still owns final cleanup.
      }
    }
  }
  if ($WebProcess -and -not $WebProcess.HasExited) {
    & taskkill.exe /PID $WebProcess.Id /T /F *> $null
  }
  if ($OwnedOllama -and -not $OwnedOllama.HasExited) {
    Stop-Process -Id $OwnedOllama.Id -Force
  }
}
