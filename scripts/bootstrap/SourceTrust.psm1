Set-StrictMode -Version Latest

function Get-JsonCodrSourceEvidence {
  [CmdletBinding()]
  param(
    [Parameter(Mandatory = $true)]
    [ValidateNotNullOrEmpty()]
    [string]$Root,
    [switch]$DevelopmentSource
  )

  $resolvedRoot = Resolve-Path -LiteralPath $Root -ErrorAction Stop
  $manifestDigest = Get-JsonCodrBootstrapManifestDigest -Root $resolvedRoot.Path
  $evidence = [ordered]@{
    normalizedRemote = $null
    commit = $null
    tree = $null
    manifestDigest = $manifestDigest
    trustState = 'untrusted'
    reason = 'no Git repository found'
  }

  $topLevel = Invoke-JsonCodrGit -Root $resolvedRoot.Path -Arguments @('rev-parse', '--show-toplevel')
  if ($topLevel.ExitCode -ne 0) {
    if ($DevelopmentSource) {
      $evidence.trustState = 'development'
      $evidence.reason = 'development source override requested'
    }
    return [pscustomobject]$evidence
  }

  $commit = Invoke-JsonCodrGit -Root $resolvedRoot.Path -Arguments @('rev-parse', 'HEAD')
  $tree = Invoke-JsonCodrGit -Root $resolvedRoot.Path -Arguments @('rev-parse', 'HEAD^{tree}')
  if ($commit.ExitCode -eq 0) { $evidence.commit = $commit.Output.Trim() }
  if ($tree.ExitCode -eq 0) { $evidence.tree = $tree.Output.Trim() }

  $origin = Invoke-JsonCodrGit -Root $resolvedRoot.Path -Arguments @('config', '--get', 'remote.origin.url')
  if ($origin.ExitCode -eq 0 -and -not [string]::IsNullOrWhiteSpace($origin.Output)) {
    $evidence.normalizedRemote = ConvertTo-JsonCodrNormalizedRemote -Remote $origin.Output.Trim()
  }

  if ($DevelopmentSource) {
    $evidence.trustState = 'development'
    $evidence.reason = 'development source override requested'
    return [pscustomobject]$evidence
  }

  if ($commit.ExitCode -ne 0 -or $tree.ExitCode -ne 0) {
    $evidence.reason = 'HEAD commit or tree is unavailable'
    return [pscustomobject]$evidence
  }
  if ($origin.ExitCode -ne 0 -or [string]::IsNullOrWhiteSpace($origin.Output)) {
    $evidence.reason = "trusted remote 'origin' is not configured"
    return [pscustomobject]$evidence
  }

  $status = Invoke-JsonCodrGit -Root $resolvedRoot.Path -Arguments @('status', '--porcelain', '--untracked-files=normal')
  if ($status.ExitCode -ne 0) {
    $evidence.reason = 'working tree status is unavailable'
    return [pscustomobject]$evidence
  }
  if (-not [string]::IsNullOrWhiteSpace($status.Output)) {
    $evidence.reason = 'working tree is dirty'
    return [pscustomobject]$evidence
  }

  $reachable = Invoke-JsonCodrGit -Root $resolvedRoot.Path -Arguments @('branch', '-r', '--contains', $evidence.commit)
  $originReference = @($reachable.Output -split "`r?`n" | ForEach-Object { $_.Trim() } | Where-Object { $_ -like 'origin/*' })
  if ($reachable.ExitCode -ne 0 -or $originReference.Count -eq 0) {
    $evidence.reason = 'commit is not reachable from origin'
    return [pscustomobject]$evidence
  }

  $evidence.trustState = 'trusted'
  $evidence.reason = 'clean commit is reachable from origin'
  return [pscustomobject]$evidence
}

function Get-JsonCodrBootstrapManifestDigest {
  [CmdletBinding()]
  param([Parameter(Mandatory = $true)][string]$Root)

  $manifestPaths = @(
    'config/runtime.json',
    'config/bootstrap-prerequisites.json',
    'config/bootstrap-models.json',
    'requirements-lock.txt'
  )
  $lines = foreach ($relativePath in $manifestPaths) {
    $path = Join-Path $Root $relativePath
    if (Test-Path -LiteralPath $path -PathType Leaf) {
      $fileHash = (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant()
      "$relativePath`:$fileHash"
    }
  }
  $payload = [Text.Encoding]::UTF8.GetBytes(($lines -join "`n"))
  $hasher = [Security.Cryptography.SHA256]::Create()
  try {
    return ([BitConverter]::ToString($hasher.ComputeHash($payload))).Replace('-', '').ToLowerInvariant()
  } finally {
    $hasher.Dispose()
  }
}

function ConvertTo-JsonCodrNormalizedRemote {
  [CmdletBinding()]
  param([Parameter(Mandatory = $true)][string]$Remote)

  $normalized = $Remote.Trim()
  if ($normalized -match '^[^@/:]+@([^:]+):(.+)$') {
    $normalized = "$($Matches[1])/$($Matches[2])"
  } else {
    $uri = $null
    if ([Uri]::TryCreate($normalized, [UriKind]::Absolute, [ref]$uri)) {
      if ($uri.Scheme -eq 'file') {
        $normalized = $uri.LocalPath
      } else {
        $normalized = "$($uri.Host)$($uri.AbsolutePath)"
      }
    }
  }
  return ($normalized.Replace('\', '/').TrimEnd('/') -replace '\.git$', '')
}

function Invoke-JsonCodrGit {
  [CmdletBinding()]
  param(
    [Parameter(Mandatory = $true)][string]$Root,
    [Parameter(Mandatory = $true)][string[]]$Arguments
  )

  $previousErrorActionPreference = $ErrorActionPreference
  $ErrorActionPreference = 'Continue'
  try {
    $output = & git -C $Root @Arguments 2>$null
    $exitCode = $LASTEXITCODE
  } finally {
    $ErrorActionPreference = $previousErrorActionPreference
  }
  [pscustomobject]@{
    ExitCode = $exitCode
    Output = (@($output) -join "`n").Trim()
  }
}

Export-ModuleMember -Function Get-JsonCodrSourceEvidence
