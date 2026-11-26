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
    if ($component.PSObject.Properties.Name -contains 'condition' -and $component.condition -ne 'intel_npu') {
      throw "Bootstrap manifest condition is invalid: $($component.condition)"
    }
    if ($component.PSObject.Properties.Name -contains 'version_selector' -and [string]$component.version_selector -notmatch '^-[0-9]+\.[0-9]+$') {
      throw "Bootstrap manifest version selector is invalid: $($component.version_selector)"
    }
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

function Import-JsonCodrAcceleratorManifest {
  [CmdletBinding()]
  param([Parameter(Mandatory=$true)][string]$Root)
  $path = Join-Path $Root 'config\bootstrap-accelerators.json'
  try { $manifest = Get-Content -LiteralPath $path -Raw | ConvertFrom-Json } catch { throw "Bootstrap accelerator manifest is invalid: $path" }
  if($manifest.schema_version -ne '1' -or @($manifest.providers).Count -lt 1){ throw 'Bootstrap accelerator manifest has an unsupported schema.' }
  foreach($provider in @($manifest.providers)){
    if($provider.condition -ne 'intel_npu' -or $provider.provider -ne 'openvino' -or $provider.device -ne 'NPU' -or [bool]$provider.installs_driver){
      throw 'Bootstrap accelerator manifest contains an unsupported provider policy.'
    }
    if([string]$provider.model.revision -notmatch '^[0-9a-f]{40}$' -or [int64]$provider.model.maximum_download_bytes -le 0 -or @($provider.model.artifacts).Count -lt 1){
      throw 'Bootstrap accelerator model policy is incomplete.'
    }
    foreach($artifact in @($provider.model.artifacts)){
      if([string]$artifact.sha256 -notmatch '^[0-9a-f]{64}$' -or [int64]$artifact.size -le 0){ throw 'Bootstrap accelerator artifact policy is incomplete.' }
    }
  }
  return $manifest
}

Export-ModuleMember -Function Import-JsonCodrBootstrapManifest,Import-JsonCodrModelManifest,Import-JsonCodrAcceleratorManifest
