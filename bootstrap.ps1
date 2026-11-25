[CmdletBinding()]
param(
  [switch]$Check,
  [switch]$Repair,
  [switch]$NoStart,
  [switch]$NoGitHub,
  [switch]$Json,
  [switch]$DevelopmentSource
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path

function Write-BootstrapProgress([string]$Message) { if(-not $Json){ [Console]::Error.WriteLine($Message) } }
function New-BootstrapResult([string]$Status,[int]$ExitCode,[string]$Detail,[object]$Source,[object]$Plan,[object]$Model,[object]$GitHub) {
  [pscustomobject][ordered]@{
    schema_version='1'; status=$Status; exit_code=$ExitCode; detail=$Detail; source=$Source; prerequisites=$Plan; ollama=$Model; github=$GitHub;
    resume_command=('powershell -NoProfile -ExecutionPolicy Bypass -File "{0}" -Repair' -f (Join-Path $Root 'bootstrap.ps1'))
  }
}
function Complete-Bootstrap([object]$Result) {
  if($Json){ [Console]::Out.WriteLine(($Result | ConvertTo-Json -Depth 8 -Compress)) } else { Write-Output ("JSON_CODR bootstrap: {0}`n{1}`nResume/repair: {2}" -f $Result.status,$Result.detail,$Result.resume_command) }
  exit ([int]$Result.exit_code)
}

try {
  if([Environment]::OSVersion.Platform -ne [PlatformID]::Win32NT -or -not [Environment]::Is64BitOperatingSystem -or [Environment]::OSVersion.Version.Build -lt 22000){
    Complete-Bootstrap (New-BootstrapResult 'BLOCKED' 20 'JSON_CODR bootstrap supports Windows 11 x64 only.' $null $null $null $null)
  }
  $modules = 'Manifest.psm1','Planner.psm1','Install.psm1','Materialize.psm1','Lifecycle.psm1','Identity.psm1','Proof.psm1','GitHub.psm1','SourceTrust.psm1','WorkspaceState.psm1'
  foreach($module in $modules){ Import-Module (Join-Path $Root (Join-Path 'scripts\bootstrap' $module)) -Force }
  $runtimePath = Join-Path $Root 'config\runtime.json'
  $runtime = Get-Content -LiteralPath $runtimePath -Raw | ConvertFrom-Json
  if($runtime.host -ne '127.0.0.1' -or [int]$runtime.port -ne 8765){ throw 'Canonical runtime is not loopback-only on port 8765.' }
  $dataRoot = if($env:JSON_CODR_DATA_ROOT){$env:JSON_CODR_DATA_ROOT}else{Join-Path $env:LOCALAPPDATA $runtime.default_roots.data_root_segment}
  if($Repair){
    Write-BootstrapProgress 'Migrating legacy workspace runtime state to the external data root with hash verification.'
    $workspaceState = Move-JsonCodrWorkspaceState -Root $Root -DataRoot $dataRoot
    if($workspaceState.status -eq 'migrated'){
      Write-BootstrapProgress ("Preserved legacy workspace state at {0}; receipt: {1}" -f $workspaceState.destination,$workspaceState.receipt_path)
    }
  }
  $source = Get-JsonCodrSourceEvidence -Root $Root -DevelopmentSource:$DevelopmentSource
  if($source.trustState -eq 'untrusted'){
    Complete-Bootstrap (New-BootstrapResult 'BLOCKED' 21 ("Trusted source validation failed: {0}. Use -DevelopmentSource only for explicitly unverified local development." -f $source.reason) $source $null $null $null)
  }
  $manifest = Import-JsonCodrBootstrapManifest -Root $Root
  $plan = Get-JsonCodrBootstrapPlan -Manifest $manifest -Root $Root
  $model = Test-JsonCodrOllamaModel -Root $Root
  $github = Test-JsonCodrGitHubReadiness -Root $Root -NoGitHub:$NoGitHub
  if($Check){
    $detail = 'Read-only diagnostics completed; no installation, configuration, model, credential, process, or GitHub changes were made.'
    $status = if($model.state -eq 'blocked' -or $github.state -eq 'blocked'){'BLOCKED'}elseif($model.state -ne 'ready' -or ($github.state -ne 'ready' -and -not $NoGitHub)){'ACTION REQUIRED'}else{if($NoGitHub){'READY (LOCAL ONLY)'}else{'READY'}}
    $code = if($status -like 'READY*'){0}elseif($status -eq 'ACTION REQUIRED'){10}else{30}
    Complete-Bootstrap (New-BootstrapResult $status $code $detail $source $plan $model $github)
  }
  Write-BootstrapProgress 'Installing only missing allowlisted prerequisites through WinGet.'
  Invoke-JsonCodrInstallPlan -Plan $plan -Repair:$Repair
  $environment = Initialize-JsonCodrRuntime -Root $Root -Runtime $runtime -Source $source -DevelopmentSource:$DevelopmentSource
  if($NoStart){ Complete-Bootstrap (New-BootstrapResult 'ACTION REQUIRED' 10 'Static prerequisites and isolated runtime are ready. Start/prove the local service with bootstrap without -NoStart.' $source $plan $model $github) }
  $model = Test-JsonCodrOllamaModel -Root $Root -AllowPull -Interactive:([Environment]::UserInteractive)
  if($model.state -ne 'ready'){ Complete-Bootstrap (New-BootstrapResult 'ACTION REQUIRED' 10 $model.detail $source $plan $model $github) }
  $running = Start-JsonCodrSafely -Runtime $runtime -Environment $environment
  if(-not $running.reused){ Initialize-JsonCodrAdministrator -Runtime $runtime -Environment $environment -DataRoot $dataRoot }
  $github = Test-JsonCodrGitHubReadiness -Root $Root -NoGitHub:$NoGitHub -Interactive:([Environment]::UserInteractive)
  if($github.state -ne 'ready' -and -not $NoGitHub){ Complete-Bootstrap (New-BootstrapResult 'ACTION REQUIRED' 10 $github.detail $source $plan $model $github) }
  $status = if($NoGitHub){'READY (LOCAL ONLY)'}else{'READY'}
  Complete-Bootstrap (New-BootstrapResult $status 0 'Local loopback service, permanent revocable non-production Administrator, Ollama, and selected GitHub readiness were proven.' $source $plan $model $github)
} catch {
  Complete-Bootstrap (New-BootstrapResult 'BLOCKED' 30 $_.Exception.Message $null $null $null $null)
}
