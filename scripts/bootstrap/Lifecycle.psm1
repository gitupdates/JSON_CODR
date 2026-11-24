Set-StrictMode -Version Latest

function Get-JsonCodrPortOwner {
  [CmdletBinding()]
  param([Parameter(Mandatory=$true)][int]$Port)
  $owner = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
  if (-not $owner) { return $null }
  $process = Get-Process -Id $owner.OwningProcess -ErrorAction SilentlyContinue
  [pscustomobject]@{ pid=$owner.OwningProcess; process=if($process){$process.ProcessName}else{'unknown'} }
}

function Test-JsonCodrHealth {
  [CmdletBinding()]
  param([Parameter(Mandatory=$true)]$Runtime)
  $nonce = [Guid]::NewGuid().ToString('N')
  try { $response = Invoke-RestMethod -Uri ("http://{0}:{1}{2}" -f $Runtime.host,$Runtime.port,$Runtime.api_paths.health) -Headers @{ 'x-json-codr-health-nonce'=$nonce } -TimeoutSec 3 } catch { return $null }
  if ($response.health_nonce -ne $nonce -or $response.app_version -ne $Runtime.version) { return $null }
  return $response
}

function Start-JsonCodrSafely {
  [CmdletBinding()]
  param([Parameter(Mandatory=$true)]$Runtime,[Parameter(Mandatory=$true)]$Environment)
  $owner = Get-JsonCodrPortOwner -Port ([int]$Runtime.port)
  $health = Test-JsonCodrHealth -Runtime $Runtime
  if ($owner -and -not $health) { throw "Port $($Runtime.port) is owned by $($owner.process) (PID $($owner.pid)); it was not reused or stopped." }
  if ($health) { return [pscustomobject]@{ reused=$true; health=$health } }
  $argumentList = @('-m','uvicorn','web_app.app:app','--host',$Runtime.host,'--port',[string]$Runtime.port)
  $process = Start-Process -FilePath $Environment.python -ArgumentList $argumentList -WorkingDirectory $Environment.root -WindowStyle Hidden -PassThru
  for($i=0;$i -lt 20;$i++){ Start-Sleep -Milliseconds 500; $health=Test-JsonCodrHealth -Runtime $Runtime; if($health){ return [pscustomobject]@{ reused=$false; pid=$process.Id; health=$health } }; if($process.HasExited){ break } }
  throw 'JSON_CODR did not provide a verified health response; bootstrap did not terminate any process.'
}

Export-ModuleMember -Function Get-JsonCodrPortOwner,Test-JsonCodrHealth,Start-JsonCodrSafely
