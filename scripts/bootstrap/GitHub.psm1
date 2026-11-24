Set-StrictMode -Version Latest

function Test-JsonCodrGitHubReadiness {
  [CmdletBinding()]
  param([Parameter(Mandatory=$true)][string]$Root,[switch]$NoGitHub,[switch]$Interactive)
  if($NoGitHub){ return [pscustomobject]@{ state='local-only'; detail='GitHub proof explicitly skipped.' } }
  $gh = Get-Command gh.exe -ErrorAction SilentlyContinue
  if(-not $gh){ return [pscustomobject]@{ state='action-required'; detail='GitHub CLI is not installed.' } }
  & $gh.Source auth status --hostname github.com 2>$null
  if($LASTEXITCODE -ne 0){ if($Interactive){ & $gh.Source auth login --hostname github.com --web --git-protocol https }; return [pscustomobject]@{ state='action-required'; detail='Sign in using gh auth login --hostname github.com --web, then rerun.' } }
  $user = & $gh.Source api --hostname github.com user 2>$null | ConvertFrom-Json
  if(-not $user.login){ return [pscustomobject]@{ state='action-required'; detail='GitHub did not return an account.' } }
  $remote = & git -C $Root remote get-url origin 2>$null
  if(-not $remote){ return [pscustomobject]@{ state='action-required'; detail='No origin remote is configured for read-only proof.' } }
  & git -C $Root ls-remote --heads $remote *> $null
  if($LASTEXITCODE -ne 0){ return [pscustomobject]@{ state='blocked'; detail='Read-only git ls-remote proof failed.' } }
  return [pscustomobject]@{ state='ready'; account=[string]$user.login; detail='Read-only GitHub identity and remote proof succeeded.' }
}

Export-ModuleMember -Function Test-JsonCodrGitHubReadiness
