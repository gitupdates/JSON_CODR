[CmdletBinding()]
param([switch]$DevelopmentSource)

$root = Split-Path -Parent $PSScriptRoot
& (Join-Path $root 'bootstrap.ps1') -Check -NoGitHub -DevelopmentSource:$DevelopmentSource -Json
exit $LASTEXITCODE
