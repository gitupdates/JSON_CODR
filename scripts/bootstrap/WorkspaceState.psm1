Set-StrictMode -Version Latest

function Get-JsonCodrFileSha256 {
  [CmdletBinding()]
  param([Parameter(Mandatory=$true)][string]$Path)

  $stream = [IO.File]::Open(
    $Path,
    [IO.FileMode]::Open,
    [IO.FileAccess]::Read,
    ([IO.FileShare]::ReadWrite -bor [IO.FileShare]::Delete)
  )
  $hasher = [Security.Cryptography.SHA256]::Create()
  try {
    return ([BitConverter]::ToString($hasher.ComputeHash($stream))).Replace('-', '').ToLowerInvariant()
  } finally {
    $hasher.Dispose()
    $stream.Dispose()
  }
}

function Get-JsonCodrMigrationManifest {
  [CmdletBinding()]
  param([Parameter(Mandatory=$true)][string]$Root)

  $resolved = Resolve-Path -LiteralPath $Root -ErrorAction Stop
  $rootItem = Get-Item -LiteralPath $resolved.Path -Force -ErrorAction Stop
  if (($rootItem.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
    throw "Workspace state migration rejects reparse point: $($rootItem.FullName)"
  }
  if (-not $rootItem.PSIsContainer) { throw "Workspace state migration root is not a directory: $($rootItem.FullName)" }

  $pending = [Collections.Generic.Queue[IO.DirectoryInfo]]::new()
  $pending.Enqueue([IO.DirectoryInfo]::new($rootItem.FullName))
  $files = [Collections.Generic.List[object]]::new()
  while ($pending.Count -gt 0) {
    $directory = $pending.Dequeue()
    foreach ($item in $directory.EnumerateFileSystemInfos()) {
      if (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
        throw "Workspace state migration rejects reparse point: $($item.FullName)"
      }
      if (($item.Attributes -band [IO.FileAttributes]::Directory) -ne 0) {
        $pending.Enqueue([IO.DirectoryInfo]$item)
        continue
      }
      $rootPath = $rootItem.FullName.TrimEnd('\', '/')
      $rootPrefix = $rootPath + [IO.Path]::DirectorySeparatorChar
      if (-not $item.FullName.StartsWith($rootPrefix, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Workspace state migration path escapes its source: $($item.FullName)"
      }
      $relative = $item.FullName.Substring($rootPrefix.Length).Replace('\', '/')
      $files.Add([pscustomobject][ordered]@{
        relative_path = $relative
        size = [Int64]$item.Length
        sha256 = Get-JsonCodrFileSha256 -Path $item.FullName
      })
    }
  }
  return @($files | Sort-Object relative_path)
}

function Test-JsonCodrMigrationContent {
  [CmdletBinding()]
  param(
    [Parameter(Mandatory=$true)][string]$Source,
    [Parameter(Mandatory=$true)][string]$Destination
  )

  $sourceFiles = @(Get-JsonCodrMigrationManifest -Root $Source)
  $destinationFiles = @(Get-JsonCodrMigrationManifest -Root $Destination)
  if ($sourceFiles.Count -ne $destinationFiles.Count) {
    throw "Migration hash verification failed: file count changed."
  }
  $verified = [Collections.Generic.List[object]]::new()
  for ($index = 0; $index -lt $sourceFiles.Count; $index++) {
    $sourceFile = $sourceFiles[$index]
    $destinationFile = $destinationFiles[$index]
    if (
      $sourceFile.relative_path -ne $destinationFile.relative_path -or
      $sourceFile.size -ne $destinationFile.size -or
      $sourceFile.sha256 -ne $destinationFile.sha256
    ) {
      throw "Migration hash verification failed for $($sourceFile.relative_path)."
    }
    $verified.Add([pscustomobject][ordered]@{
      relative_path = $sourceFile.relative_path
      size = $sourceFile.size
      source_sha256 = $sourceFile.sha256
      destination_sha256 = $destinationFile.sha256
    })
  }
  return @($verified)
}

function Get-JsonCodrMigrationId {
  [CmdletBinding()]
  param([Parameter(Mandatory=$true)][AllowEmptyCollection()][object[]]$Manifest)

  $lines = @($Manifest | ForEach-Object { "$($_.relative_path)`0$($_.size)`0$($_.sha256)" })
  $payload = [Text.Encoding]::UTF8.GetBytes(($lines -join "`n"))
  $hasher = [Security.Cryptography.SHA256]::Create()
  try {
    $digest = ([BitConverter]::ToString($hasher.ComputeHash($payload))).Replace('-', '').ToLowerInvariant()
  } finally {
    $hasher.Dispose()
  }
  return "workspace-tmp-$digest"
}

function Move-JsonCodrWorkspaceState {
  [CmdletBinding()]
  param(
    [Parameter(Mandatory=$true)][string]$Root,
    [Parameter(Mandatory=$true)][string]$DataRoot
  )

  $resolvedRoot = (Resolve-Path -LiteralPath $Root -ErrorAction Stop).Path.TrimEnd('\', '/')
  $resolvedDataRoot = [IO.Path]::GetFullPath($DataRoot).TrimEnd('\', '/')
  $rootPrefix = $resolvedRoot + [IO.Path]::DirectorySeparatorChar
  if ($resolvedDataRoot.Equals($resolvedRoot, [StringComparison]::OrdinalIgnoreCase) -or
      $resolvedDataRoot.StartsWith($rootPrefix, [StringComparison]::OrdinalIgnoreCase)) {
    throw 'JSON_CODR data root must be outside the trusted source checkout.'
  }

  $source = Join-Path $resolvedRoot '.tmp'
  if (-not (Test-Path -LiteralPath $source)) {
    return [pscustomobject][ordered]@{
      schema_version = '1'; status = 'not-needed'; source = $source; destination = $null
      receipt_path = $null; files = @(); source_removed = $false
    }
  }
  $manifest = @(Get-JsonCodrMigrationManifest -Root $source)
  $migrationId = Get-JsonCodrMigrationId -Manifest $manifest
  $migrationRoot = Join-Path $resolvedDataRoot 'workspace-migrations'
  $receiptRoot = Join-Path $resolvedDataRoot 'migration-receipts'
  $destination = Join-Path $migrationRoot $migrationId
  New-Item -ItemType Directory -Path $migrationRoot -Force | Out-Null
  New-Item -ItemType Directory -Path $receiptRoot -Force | Out-Null

  foreach ($stale in @(Get-ChildItem -LiteralPath $migrationRoot -Force -Directory -ErrorAction Stop | Where-Object { $_.Name -like '.*.staging' })) {
    if (($stale.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
      throw "Workspace state migration rejects reparse staging path: $($stale.FullName)"
    }
    Remove-Item -LiteralPath $stale.FullName -Recurse -Force
  }

  if (-not (Test-Path -LiteralPath $destination)) {
    $staging = Join-Path $migrationRoot ".$migrationId.$([Guid]::NewGuid().ToString('N')).staging"
    New-Item -ItemType Directory -Path $staging -ErrorAction Stop | Out-Null
    try {
      foreach ($item in $manifest) {
        $sourceFile = Join-Path $source $item.relative_path
        $destinationFile = Join-Path $staging $item.relative_path
        $destinationDirectory = Split-Path -Parent $destinationFile
        New-Item -ItemType Directory -Path $destinationDirectory -Force | Out-Null
        [IO.File]::Copy($sourceFile, $destinationFile, $false)
      }
      [void](Test-JsonCodrMigrationContent -Source $source -Destination $staging)
      Move-Item -LiteralPath $staging -Destination $destination -ErrorAction Stop
    } catch {
      if (Test-Path -LiteralPath $staging) { Remove-Item -LiteralPath $staging -Recurse -Force }
      throw
    }
  }

  $verified = @(Test-JsonCodrMigrationContent -Source $source -Destination $destination)
  $sourceItem = Get-Item -LiteralPath $source -Force -ErrorAction Stop
  if (($sourceItem.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0 -or
      [IO.Path]::GetFullPath($sourceItem.FullName) -ne [IO.Path]::GetFullPath((Join-Path $resolvedRoot '.tmp'))) {
    throw 'Workspace state source changed before removal.'
  }
  Remove-Item -LiteralPath $sourceItem.FullName -Recurse -Force

  $receiptPath = Join-Path $receiptRoot "$migrationId.json"
  $receipt = [pscustomobject][ordered]@{
    schema_version = '1'
    migration_id = $migrationId
    status = 'migrated'
    source = $source
    destination = $destination
    migrated_at = [DateTimeOffset]::UtcNow.ToString('o')
    source_removed = $true
    receipt_path = $receiptPath
    files = $verified
  }
  $temporaryReceipt = "$receiptPath.$([Guid]::NewGuid().ToString('N')).tmp"
  try {
    [IO.File]::WriteAllText($temporaryReceipt, ($receipt | ConvertTo-Json -Depth 8 -Compress), [Text.UTF8Encoding]::new($false))
    Move-Item -LiteralPath $temporaryReceipt -Destination $receiptPath -Force
  } finally {
    if (Test-Path -LiteralPath $temporaryReceipt) { Remove-Item -LiteralPath $temporaryReceipt -Force }
  }
  return $receipt
}

Export-ModuleMember -Function Move-JsonCodrWorkspaceState,Test-JsonCodrMigrationContent
