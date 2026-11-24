Set-StrictMode -Version Latest

function Get-JsonCodrBootstrapPlan {
  [CmdletBinding()]
  param([Parameter(Mandatory=$true)]$Manifest,[Parameter(Mandatory=$true)][string]$Root)
  $components = foreach ($component in @($Manifest.components)) {
    $command = Get-Command $component.command -ErrorAction SilentlyContinue | Select-Object -First 1
    [pscustomobject]@{ id=$component.id; package=$component.package; publisher=$component.publisher; command=$component.command; installed=[bool]$command; path=if($command){$command.Source}else{$null}; action=if($command){'probe'}else{'install'} }
  }
  $driveName = ([IO.Path]::GetPathRoot((Resolve-Path $Root).Path)).TrimEnd(':','\')
  $free = (Get-PSDrive -Name $driveName -ErrorAction SilentlyContinue).Free
  [pscustomobject]@{ schema_version='1'; root=(Resolve-Path $Root).Path; components=@($components); free_bytes=$free; requires_elevation=$false }
}

Export-ModuleMember -Function Get-JsonCodrBootstrapPlan
