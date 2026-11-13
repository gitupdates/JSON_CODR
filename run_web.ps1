param(
  [switch]$NoBrowser,
  [switch]$ValidateOnly
)

$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$HostAddress = '127.0.0.1'
$Port = 8765
$Url = "http://${HostAddress}:$Port"
$Python = (Get-Command python -ErrorAction Stop).Source
$Ollama = (Get-Command ollama -ErrorAction Stop).Source

if ($ValidateOnly) {
  [pscustomobject]@{
    host = $HostAddress
    port = $Port
    url = $Url
    python = $Python
    ollama = $Ollama
    modelStore = $env:JSON_CODR_MODELS
  } | ConvertTo-Json
  exit 0
}

$env:PYTHONUTF8 = '1'
$env:PYTHONIOENCODING = 'utf-8'
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

  $WebProcess = Start-Process -FilePath $Python -ArgumentList @(
    '-m', 'uvicorn', 'web_app.app:app', '--host', $HostAddress, '--port', $Port
  ) -WorkingDirectory $Root -WindowStyle Hidden -PassThru

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

  Write-Host "JSON_CODR V1.0.0 is running at $Url"
  Write-Host 'Press Ctrl+C to stop the local web server.'
  if (-not $NoBrowser) { Start-Process $Url }
  Wait-Process -Id $WebProcess.Id
} finally {
  if ($WebProcess -and -not $WebProcess.HasExited) {
    Stop-Process -Id $WebProcess.Id -Force
  }
  if ($OwnedOllama -and -not $OwnedOllama.HasExited) {
    Stop-Process -Id $OwnedOllama.Id -Force
  }
}
