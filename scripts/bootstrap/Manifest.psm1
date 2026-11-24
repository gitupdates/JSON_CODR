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
  if ($manifest.schema_version -ne '1' -or @($manifest.models).Count -lt 1) { throw 'Bootstrap model manifest has an unsupported schema.' }
  $model = @($manifest.models)[0]
  if ([string]::IsNullOrWhiteSpace([string]$model.name) -or [Int64]$model.maximum_download_bytes -le 0) { throw 'Bootstrap model manifest is incomplete.' }
  return $manifest
}

Export-ModuleMember -Function Import-JsonCodrBootstrapManifest,Import-JsonCodrModelManifest
