Set-StrictMode -Version Latest

function Test-JsonCodrOllamaModel {
  [CmdletBinding()]
  param([Parameter(Mandatory=$true)][string]$Root,[switch]$AllowPull,[switch]$Interactive)
  $manifest = Import-JsonCodrModelManifest -Root $Root
  $model = @($manifest.models)[0]
  $ollama = Get-Command ollama.exe -ErrorAction SilentlyContinue | Select-Object -First 1
  if(-not $ollama){ return [pscustomobject]@{ state='blocked'; detail='Ollama is not installed.'; model=$model.name } }
  try { $tags = Invoke-RestMethod -Uri 'http://127.0.0.1:11434/api/tags' -TimeoutSec 3 } catch { return [pscustomobject]@{ state='action-required'; detail='Start Ollama through its supported local application, then rerun bootstrap.'; model=$model.name } }
  $installed = @($tags.models | ForEach-Object { $_.name }) -contains $model.name
  if(-not $installed -and $AllowPull -and $Interactive){
    $answer = Read-Host "Pull reviewed model $($model.name) (up to $([math]::Round(([Int64]$model.maximum_download_bytes / 1GB),1)) GB)? [y/N]"
    if($answer -match '^(y|yes)$'){ & $ollama.Source pull $model.name; $installed = ($LASTEXITCODE -eq 0) }
  }
  if(-not $installed){ return [pscustomobject]@{ state='action-required'; detail="Reviewed model $($model.name) is not installed. Rerun interactively to confirm its pull."; model=$model.name } }
  return [pscustomobject]@{ state='ready'; detail='A reviewed Ollama model is installed.'; model=$model.name }
}

Export-ModuleMember -Function Test-JsonCodrOllamaModel
