Set-StrictMode -Version Latest

function New-JsonCodrModelPolicyResult {
  [CmdletBinding()]
  param(
    [Parameter(Mandatory=$true)][string]$State,
    [Parameter(Mandatory=$true)][string]$Detail,
    [object]$PolicyVersion,
    [object]$Model,
    [object]$Digest,
    [bool]$ProbePassed = $false,
    [object]$ProbeDetail,
    [object]$FallbackReason
  )
  return [pscustomobject][ordered]@{
    state = $State
    detail = $Detail
    policy_version = $PolicyVersion
    model = $Model
    digest = $Digest
    probe_passed = $ProbePassed
    probe_detail = $ProbeDetail
    fallback_reason = $FallbackReason
  }
}

function Invoke-JsonCodrModelPolicyEvaluation {
  [CmdletBinding()]
  param(
    [Parameter(Mandatory=$true)][string]$Root,
    [Parameter(Mandatory=$true)][object]$Manifest
  )
  $python = Get-Command python.exe -ErrorAction SilentlyContinue | Select-Object -First 1
  if(-not $python){
    return New-JsonCodrModelPolicyResult -State 'action-required' -Detail 'Python is required to evaluate the reviewed model policy.' -PolicyVersion $Manifest.policy_version -Model $null -Digest $null -ProbeDetail 'coding probe did not run' -FallbackReason 'Python is unavailable'
  }
  $policyPath = Join-Path $Root 'config\bootstrap-models.json'
  $evaluator = Join-Path $Root 'web_app\core\model_policy.py'
  try {
    $output = @(& $python.Source $evaluator --policy $policyPath --endpoint 'http://127.0.0.1:11434' 2>&1)
    $exitCode = $LASTEXITCODE
    $text = ($output | ForEach-Object { [string]$_ }) -join "`n"
    $result = $text | ConvertFrom-Json -ErrorAction Stop
  } catch {
    return New-JsonCodrModelPolicyResult -State 'action-required' -Detail ("Reviewed model policy evaluation failed: {0}" -f $_.Exception.Message) -PolicyVersion $Manifest.policy_version -Model $null -Digest $null -ProbeDetail 'coding probe did not run' -FallbackReason 'policy evaluator failed'
  }
  if($exitCode -notin 0,10){
    return New-JsonCodrModelPolicyResult -State 'action-required' -Detail 'Reviewed model policy evaluator exited unexpectedly.' -PolicyVersion $Manifest.policy_version -Model $null -Digest $null -ProbeDetail 'coding probe did not run' -FallbackReason 'policy evaluator failed'
  }
  return $result
}

function Test-JsonCodrOllamaModel {
  [CmdletBinding()]
  param([Parameter(Mandatory=$true)][string]$Root,[switch]$AllowPull,[switch]$Interactive)
  $manifest = Import-JsonCodrModelManifest -Root $Root
  $preferred = @($manifest.models)[0]
  $ollama = Get-Command ollama.exe -ErrorAction SilentlyContinue | Select-Object -First 1
  if(-not $ollama){
    return New-JsonCodrModelPolicyResult -State 'blocked' -Detail 'Ollama is not installed.' -PolicyVersion $manifest.policy_version -Model $preferred.name -Digest $preferred.digest -ProbeDetail 'coding probe did not run' -FallbackReason 'Ollama is unavailable'
  }

  $result = Invoke-JsonCodrModelPolicyEvaluation -Root $Root -Manifest $manifest
  if($result.state -eq 'ready' -or -not $AllowPull){ return $result }

  # Models in this versioned manifest are the only artifacts approved for automatic first-run retrieval.
  # A mutable tag is never trusted by itself: the evaluator rechecks its exact digest after the pull.
  & $ollama.Source pull $preferred.name | Out-Null
  if($LASTEXITCODE -ne 0){
    return New-JsonCodrModelPolicyResult -State 'action-required' -Detail ("Automatic pull failed for reviewed model {0}." -f $preferred.name) -PolicyVersion $manifest.policy_version -Model $preferred.name -Digest $preferred.digest -ProbeDetail 'coding probe did not run' -FallbackReason $result.detail
  }
  $verified = Invoke-JsonCodrModelPolicyEvaluation -Root $Root -Manifest $manifest
  if($verified.state -ne 'ready'){
    $verified.detail = "Pulled $($preferred.name), but digest-bound policy verification still failed: $($verified.detail)"
  }
  return $verified
}

Export-ModuleMember -Function Test-JsonCodrOllamaModel
