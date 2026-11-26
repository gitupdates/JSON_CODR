Set-StrictMode -Version Latest

function Get-JsonCodrBootstrapPlan {
  [CmdletBinding()]
  param(
    [Parameter(Mandatory=$true)]$Manifest,
    [Parameter(Mandatory=$true)][string]$Root,
    [hashtable]$Conditions = @{}
  )
  $components = foreach ($component in @($Manifest.components)) {
    $condition = if($component.PSObject.Properties.Name -contains 'condition'){[string]$component.condition}else{$null}
    $eligible = [string]::IsNullOrWhiteSpace($condition) -or ($Conditions.ContainsKey($condition) -and [bool]$Conditions[$condition])
    $command = Get-Command $component.command -ErrorAction SilentlyContinue | Select-Object -First 1
    $installed = [bool]$command
    if($eligible -and $installed -and $component.PSObject.Properties.Name -contains 'version_selector'){
      & $command.Source ([string]$component.version_selector) -c 'raise SystemExit(0)' 2>$null
      $installed = $LASTEXITCODE -eq 0
    }
    $action = if(-not $eligible){'skip'}elseif($installed){'probe'}else{'install'}
    [pscustomobject]@{
      id=$component.id; package=$component.package; publisher=$component.publisher; command=$component.command
      installed=$installed; path=if($command){$command.Source}else{$null}; action=$action; condition=$condition
      version_selector=if($component.PSObject.Properties.Name -contains 'version_selector'){$component.version_selector}else{$null}
    }
  }
  $driveName = ([IO.Path]::GetPathRoot((Resolve-Path $Root).Path)).TrimEnd(':','\')
  $free = (Get-PSDrive -Name $driveName -ErrorAction SilentlyContinue).Free
  [pscustomobject]@{ schema_version='1'; root=(Resolve-Path $Root).Path; components=@($components); free_bytes=$free; requires_elevation=$false }
}

Export-ModuleMember -Function Get-JsonCodrBootstrapPlan
