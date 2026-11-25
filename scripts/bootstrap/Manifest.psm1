Set-StrictMode -Version Latest

function Import-JsonCodrBootstrapManifest {
  [CmdletBinding()]
  param([Parameter(Mandatory=$true)][string]$Root)
  $path = Join-Path $Root 'config\bootstrap-prerequisites.json'
  try { $manifest = Get-Content -LiteralPath $path -Raw | ConvertFrom-Json } catch { throw "Bootstrap prerequisite manifest is invalid: $path" }
  if ($manifest.schema_version -ne '1' -or $manifest.host.architecture -ne 'x64' -or @($manifest.components).Count -lt 4) {
    throw 'Bootstrap prerequisite manifest has an unsupported schema or host.'
  }
  foreach ($component in @($manifest.components)) {
    foreach ($name in 'id','package','publisher','minimum_version','command','scope') {
      if ([string]::IsNullOrWhiteSpace([string]$component.$name)) { throw "Bootstrap manifest component is missing $name." }
    }
    if ($component.package -notmatch '^[A-Za-z0-9.-]+$') { throw "Bootstrap manifest package is invalid: $($component.package)" }
  }
  return $manifest
}

function Import-JsonCodrModelManifest {
  [CmdletBinding()]
  param([Parameter(Mandatory=$true)][string]$Root)
  $path = Join-Path $Root 'config\bootstrap-models.json'
  try { $manifest = Get-Content -LiteralPath $path -Raw | ConvertFrom-Json } catch { throw "Bootstrap model manifest is invalid: $path" }
  if ($manifest.schema_version -ne '2' -or @($manifest.models).Count -lt 2) { throw 'Bootstrap model manifest has an unsupported schema.' }
  if ([string]$manifest.policy_version -notmatch '^[0-9]{4}-[0-9]{2}-[0-9]{2}\.[0-9]+$') { throw 'Bootstrap model policy version is invalid.' }
  if ([string]::IsNullOrWhiteSpace([string]$manifest.probe.prompt) -or
      [string]::IsNullOrWhiteSpace([string]$manifest.probe.expected) -or
      [int]$manifest.probe.timeout_seconds -lt 1 -or [int]$manifest.probe.timeout_seconds -gt 120 -or
      [int]$manifest.probe.maximum_tokens -lt 1 -or [int]$manifest.probe.maximum_tokens -gt 128) {
    throw 'Bootstrap model coding probe is invalid.'
  }
  $names = @{}
  foreach($model in @($manifest.models)) {
    if ([string]::IsNullOrWhiteSpace([string]$model.name) -or
        [string]$model.digest -notmatch '^sha256:[0-9a-f]{64}$' -or
        [string]$model.purpose -ne 'reviewed local coding' -or
        [Int64]$model.maximum_download_bytes -le 0) {
      throw 'Bootstrap model manifest is incomplete.'
    }
    if($names.ContainsKey([string]$model.name)){ throw "Bootstrap model manifest contains duplicate model: $($model.name)" }
    $names[[string]$model.name] = $true
  }
  return $manifest
}

Export-ModuleMember -Function Import-JsonCodrBootstrapManifest,Import-JsonCodrModelManifest
