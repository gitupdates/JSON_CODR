Set-StrictMode -Version Latest

function Invoke-JsonCodrInstallPlan {
  [CmdletBinding(SupportsShouldProcess=$true)]
  param([Parameter(Mandatory=$true)]$Plan,[switch]$Repair)
  $pending = @($Plan.components | Where-Object { $_.action -eq 'install' })
  if($pending.Count -eq 0){ return }
  $winget = Get-Command winget.exe -ErrorAction SilentlyContinue
  if (-not $winget) {
    if(@($pending | Where-Object {[string]::IsNullOrWhiteSpace([string]$_.condition)}).Count -gt 0){
      throw 'WinGet is required. Install/repair App Installer and rerun bootstrap.'
    }
    [Console]::Error.WriteLine('Optional hardware prerequisites were skipped because WinGet is unavailable.')
    return
  }
  foreach ($item in $pending) {
    if ($PSCmdlet.ShouldProcess($item.package, 'Install approved prerequisite')) {
      try {
        & $winget.Source install --id $item.package --exact --source winget --scope user --accept-source-agreements --accept-package-agreements --disable-interactivity
        if ($LASTEXITCODE -ne 0) { throw "WinGet failed to install approved prerequisite $($item.id)." }
        $command = Get-Command $item.command -ErrorAction SilentlyContinue | Select-Object -First 1
        if (-not $command) { throw "Installed prerequisite $($item.id) cannot be reprobed." }
        if(-not [string]::IsNullOrWhiteSpace([string]$item.version_selector)){
          & $command.Source ([string]$item.version_selector) -c 'raise SystemExit(0)' 2>$null
          if($LASTEXITCODE -ne 0){ throw "Installed prerequisite $($item.id) failed its version-specific reprobe." }
        }
      } catch {
        if([string]::IsNullOrWhiteSpace([string]$item.condition)){ throw }
        [Console]::Error.WriteLine(("Optional prerequisite {0} was not installed: {1}" -f $item.id,$_.Exception.Message))
      }
    }
  }
}

Export-ModuleMember -Function Invoke-JsonCodrInstallPlan
