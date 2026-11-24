Set-StrictMode -Version Latest

function Invoke-JsonCodrInstallPlan {
  [CmdletBinding(SupportsShouldProcess=$true)]
  param([Parameter(Mandatory=$true)]$Plan,[switch]$Repair)
  $winget = Get-Command winget.exe -ErrorAction SilentlyContinue
  if (-not $winget) { throw 'WinGet is required. Install/repair App Installer and rerun bootstrap.' }
  foreach ($item in @($Plan.components | Where-Object { -not $_.installed })) {
    if ($PSCmdlet.ShouldProcess($item.package, 'Install approved prerequisite')) {
      & $winget.Source install --id $item.package --exact --source winget --scope user --accept-source-agreements --accept-package-agreements --disable-interactivity
      if ($LASTEXITCODE -ne 0) { throw "WinGet failed to install approved prerequisite $($item.id)." }
      if (-not (Get-Command $item.command -ErrorAction SilentlyContinue)) { throw "Installed prerequisite $($item.id) cannot be reprobed." }
    }
  }
}

Export-ModuleMember -Function Invoke-JsonCodrInstallPlan
