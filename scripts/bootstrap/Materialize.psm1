Set-StrictMode -Version Latest

function Initialize-JsonCodrRuntime {
  [CmdletBinding()]
  param([Parameter(Mandatory=$true)][string]$Root,[Parameter(Mandatory=$true)]$Runtime,[Parameter(Mandatory=$true)]$Source,[switch]$DevelopmentSource)
  $python = Get-Command python.exe -ErrorAction SilentlyContinue | Select-Object -First 1
  if (-not $python) { throw 'Python is not available after prerequisite installation.' }
  $version = & $python.Source -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"
  if (@($Runtime.python.host_versions) -notcontains $version) { throw "Python $version is not supported; expected $($Runtime.python.host_versions -join ' or ')." }
  $local = if($env:LOCALAPPDATA){$env:LOCALAPPDATA}else{Join-Path $HOME 'AppData\Local'}
  $lock = Join-Path $Root 'requirements-lock.txt'
  $digest = (Get-FileHash -LiteralPath $lock -Algorithm SHA256).Hash.ToLowerInvariant()
  $environmentId = "py$($version.Replace('.',''))-$($Runtime.version)-$($digest.Substring(0,12))"
  $runtimeRoot = Join-Path $local 'JSON_CODR\runtime'
  $venv = Join-Path $runtimeRoot $environmentId
  $venvPython = Join-Path $venv 'Scripts\python.exe'
  if (-not (Test-Path -LiteralPath $venvPython)) {
    New-Item -ItemType Directory -Force -Path $runtimeRoot | Out-Null
    & $python.Source -m venv $venv
    if ($LASTEXITCODE -ne 0) { throw 'Unable to create isolated JSON_CODR virtual environment.' }
    if (-not $DevelopmentSource) {
      $lockText = Get-Content -LiteralPath $lock -Raw
      if ($lockText -notmatch '(?m)^\s*[^#\s].*--hash=sha256:') { throw 'requirements-lock.txt is not hash-locked; refusing mutable dependency resolution.' }
      & $venvPython -m pip install --disable-pip-version-check --no-input --require-hashes -r $lock
    } else {
      & $venvPython -m pip install --disable-pip-version-check --no-input -r (Join-Path $Root 'requirements.txt')
    }
    if ($LASTEXITCODE -ne 0) { throw 'JSON_CODR dependency installation failed.' }
  }
  [pscustomobject]@{ environment_id=$environmentId; python=$venvPython; root=$Root; verified=([bool](-not $DevelopmentSource)); lock_digest=$digest }
}

Export-ModuleMember -Function Initialize-JsonCodrRuntime
