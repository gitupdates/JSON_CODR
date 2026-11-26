Set-StrictMode -Version Latest

function Get-JsonCodrIntelNpuHardware {
  [CmdletBinding()]
  param([object[]]$DeviceRecords)
  if($null -eq $DeviceRecords){
    try {
      $DeviceRecords = @(Get-CimInstance Win32_PnPEntity -ErrorAction Stop | Select-Object Name,Status,ConfigManagerErrorCode)
    } catch {
      return [pscustomobject]@{ condition='intel_npu'; detected=$false; devices=@(); detail='Windows device inventory was unavailable.' }
    }
  }
  $pattern = '(?i)intel(?:\(r\))?.*(?:AI Boost|AI accelerator|\bNPU\b|neural (?:processing unit|processor))'
  $devices = @($DeviceRecords | Where-Object {
    [string]$_.Name -match $pattern -and
    ($null -eq $_.ConfigManagerErrorCode -or [int]$_.ConfigManagerErrorCode -eq 0) -and
    ([string]::IsNullOrWhiteSpace([string]$_.Status) -or [string]$_.Status -eq 'OK')
  } | ForEach-Object {[string]$_.Name} | Sort-Object -Unique)
  [pscustomobject]@{
    condition='intel_npu'
    detected=($devices.Count -gt 0)
    devices=$devices
    detail=if($devices.Count -gt 0){'A healthy Intel NPU device is eligible for optional provisioning.'}else{'No healthy Intel NPU device was detected.'}
  }
}

function Initialize-JsonCodrIntelNpu {
  [CmdletBinding()]
  param(
    [Parameter(Mandatory=$true)][string]$Root,
    [Parameter(Mandatory=$true)][string]$DataRoot,
    [Parameter(Mandatory=$true)][string]$Python,
    [Parameter(Mandatory=$true)]$Hardware
  )
  if(-not [bool]$Hardware.detected){
    return [pscustomobject]@{ state='skipped'; provider='openvino'; detail=$Hardware.detail; hardware=@($Hardware.devices); drivers_modified=$false }
  }
  Push-Location $Root
  try {
    $lines = @(& $Python -m web_app.inference.intel_npu_bootstrap --data-root $DataRoot 2>&1)
    $exitCode = $LASTEXITCODE
  } finally {
    Pop-Location
  }
  $jsonLine = @($lines | ForEach-Object {[string]$_} | Where-Object {$_.TrimStart().StartsWith('{')}) | Select-Object -Last 1
  if($exitCode -ne 0 -or [string]::IsNullOrWhiteSpace($jsonLine)){
    return [pscustomobject]@{ state='unavailable'; provider='openvino'; detail='Optional Intel NPU provisioner did not return a valid result.'; hardware=@($Hardware.devices); drivers_modified=$false }
  }
  try { return $jsonLine | ConvertFrom-Json -ErrorAction Stop } catch {
    return [pscustomobject]@{ state='unavailable'; provider='openvino'; detail='Optional Intel NPU provisioner returned invalid JSON.'; hardware=@($Hardware.devices); drivers_modified=$false }
  }
}

Export-ModuleMember -Function Get-JsonCodrIntelNpuHardware,Initialize-JsonCodrIntelNpu
