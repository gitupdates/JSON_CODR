param(
  [string]$Root = $env:JSON_CODR_ROOT,
  [string]$Url = $env:JSON_CODR_URL
)

$ErrorActionPreference = 'Stop'
$PluginRelativeRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..'))
$ManifestPath = if ($env:LOCALAPPDATA) {
  Join-Path $env:LOCALAPPDATA 'JSON_CODR\installation.json'
} else {
  Join-Path $HOME '.json_codr\installation.json'
}
if (-not $Root -and (Test-Path -LiteralPath $ManifestPath)) {
  try {
    $Manifest = Get-Content -Raw -LiteralPath $ManifestPath | ConvertFrom-Json
    $ManifestRoot = [string]$Manifest.root
    if ($ManifestRoot -and (Test-Path -LiteralPath (Join-Path $ManifestRoot 'run_web.ps1'))) {
      $Root = $ManifestRoot
      if (-not $Url -and $Manifest.service_url) { $Url = [string]$Manifest.service_url }
    }
  } catch { }
}
if (-not $Root) { $Root = $PluginRelativeRoot }
if (-not $Url) { $Url = 'http://127.0.0.1:8765' }
$Launcher = Join-Path $Root 'run_web.ps1'
if (-not (Test-Path -LiteralPath $Launcher)) {
  throw "JSON_CODR launcher not found: $Launcher"
}

function Test-JsonCodrHealth {
  try {
    $Health = Invoke-RestMethod -Uri "$Url/api/health" -TimeoutSec 2
    return $Health.status -eq 'ready'
  } catch {
    return $false
  }
}

$Mutex = [Threading.Mutex]::new($false, 'Local\JSON_CODR_MCP_START_8765')
try {
  if (-not $Mutex.WaitOne([TimeSpan]::FromSeconds(45))) {
    throw 'Timed out waiting for the JSON_CODR startup lock.'
  }
  if (-not (Test-JsonCodrHealth)) {
    Start-Process -FilePath 'powershell.exe' -ArgumentList @(
      '-NoLogo',
      '-NoProfile',
      '-ExecutionPolicy',
      'Bypass',
      '-File',
      $Launcher,
      '-NoBrowser'
    ) -WorkingDirectory $Root -WindowStyle Hidden | Out-Null
    for ($Attempt = 0; $Attempt -lt 60; $Attempt++) {
      Start-Sleep -Milliseconds 500
      if (Test-JsonCodrHealth) { break }
      if ($Attempt -eq 59) { throw "JSON_CODR did not become ready at $Url." }
    }
  }
} finally {
  try { $Mutex.ReleaseMutex() } catch { }
  $Mutex.Dispose()
}

$PythonCandidates = @()
if ($env:JSON_CODR_PYTHON) { $PythonCandidates += $env:JSON_CODR_PYTHON }
$PythonCandidates += @('C:\Python315\python.exe', 'python3.15', 'python')
$Python = $null
foreach ($Candidate in $PythonCandidates) {
  $Command = Get-Command $Candidate -ErrorAction SilentlyContinue | Select-Object -First 1
  if ($Command) {
    $Python = $Command.Source
    break
  }
}
if (-not $Python) { throw 'A Python runtime for the JSON_CODR MCP adapter was not found.' }

$env:JSON_CODR_URL = $Url
$env:PYTHONPATH = $Root
& $Python -m web_app.integrations.mcp_server --base-url $Url
