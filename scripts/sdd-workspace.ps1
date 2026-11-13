[CmdletBinding()]
param(
    [Parameter(Mandatory = $true, Position = 0)]
    [string]$PlanFile
)

$ErrorActionPreference = "Stop"

if (-not (Test-Path -LiteralPath $PlanFile -PathType Leaf)) {
    throw "no such plan file: $PlanFile"
}

$planPath = (Resolve-Path -LiteralPath $PlanFile).Path
$slug = [System.IO.Path]::GetFileNameWithoutExtension($planPath)
if ([string]::IsNullOrWhiteSpace($slug) -or $slug -in @(".", "..")) {
    throw "cannot derive a workspace name from: $PlanFile"
}

$rootOutput = & git rev-parse --show-toplevel 2>&1
if ($LASTEXITCODE -ne 0) {
    throw "not inside a Git working tree: $rootOutput"
}
$root = [System.IO.Path]::GetFullPath(($rootOutput | Select-Object -First 1).Trim()).TrimEnd('\', '/')
$base = Join-Path $root ".superpowers\sdd"
$planFullPath = [System.IO.Path]::GetFullPath($planPath)
$rootPrefix = $root + [System.IO.Path]::DirectorySeparatorChar
if ($planFullPath.StartsWith($rootPrefix, [System.StringComparison]::OrdinalIgnoreCase)) {
    $planId = $planFullPath.Substring($rootPrefix.Length).Replace('\', '/')
}
else {
    $planId = $planFullPath
}

$utf8WithoutBom = New-Object System.Text.UTF8Encoding($false)

function Test-WorkspaceOwnership {
    param([Parameter(Mandatory = $true)][string]$Workspace)

    $marker = Join-Path $Workspace "plan-path"
    if (Test-Path -LiteralPath $marker) {
        return ([System.IO.File]::ReadAllText($marker).TrimEnd("`r", "`n") -ceq $planId)
    }

    [System.IO.Directory]::CreateDirectory($Workspace) | Out-Null
    [System.IO.File]::WriteAllText($marker, $planId + "`n", $utf8WithoutBom)
    return $true
}

$workspace = Join-Path $base $slug
if (-not (Test-WorkspaceOwnership -Workspace $workspace)) {
    $parent = Split-Path -Leaf (Split-Path -Parent $planFullPath)
    $workspace = Join-Path $base "$slug-$parent"
    if (-not (Test-WorkspaceOwnership -Workspace $workspace)) {
        $counter = 2
        do {
            $candidate = Join-Path $base "$slug-$parent-$counter"
            $counter += 1
        } until (Test-WorkspaceOwnership -Workspace $candidate)
        $workspace = $candidate
    }
}

[System.IO.Directory]::CreateDirectory($base) | Out-Null
$ignoreFile = Join-Path $base ".gitignore"
if (-not (Test-Path -LiteralPath $ignoreFile)) {
    [System.IO.File]::WriteAllText($ignoreFile, "*`n", $utf8WithoutBom)
}

[System.IO.Path]::GetFullPath($workspace)
