[CmdletBinding()]
param([switch]$DevelopmentSource)

$root = Split-Path -Parent $PSScriptRoot
& (Join-Path $root 'bootstrap.ps1') -Check -NoGitHub -DevelopmentSource:$DevelopmentSource -Json
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

& (Join-Path $PSScriptRoot 'verify-coding-workflow.ps1')
exit $LASTEXITCODE
