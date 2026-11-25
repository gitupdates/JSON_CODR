Set-StrictMode -Version Latest

function Initialize-JsonCodrAdministrator {
  [CmdletBinding()]
  param([Parameter(Mandatory=$true)]$Runtime,[Parameter(Mandatory=$true)]$Environment,[Parameter(Mandatory=$true)][string]$DataRoot)
  $password = Read-Host 'Create a permanent development Administrator password' -AsSecureString
  $confirm = Read-Host 'Confirm Administrator password' -AsSecureString
  $first = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($password)
  $second = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($confirm)
  try {
    $plain = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($first)
    if ($plain -ne [Runtime.InteropServices.Marshal]::PtrToStringBSTR($second)) { throw 'Administrator passwords do not match.' }
    Push-Location $Environment.root
    try {
      $plain | & $Environment.python -m scripts.bootstrap.initialize_identity --data-root $DataRoot --origin ("http://{0}:{1}" -f $Runtime.host,$Runtime.port)
    } finally {
      Pop-Location
    }
    if($LASTEXITCODE -ne 0){ throw 'Administrator initialization failed.' }
  } finally {
    if($first -ne [IntPtr]::Zero){ [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($first) }
    if($second -ne [IntPtr]::Zero){ [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($second) }
  }
}

Export-ModuleMember -Function Initialize-JsonCodrAdministrator
