[CmdletBinding()]
param(
  [string]$ServerOrigin = 'http://127.0.0.1:8765',
  [string]$ReceiptPath = '',
  [string]$Python = 'python'
)

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$sourceRoot = (Resolve-Path (Split-Path -Parent $PSScriptRoot)).Path
$runId = [Guid]::NewGuid().ToString('N')
$temporaryParent = [IO.Path]::GetFullPath([IO.Path]::GetTempPath()).TrimEnd('\')
$projectRoot = Join-Path $temporaryParent "json-codr-verifier-$runId"
$outsideRoot = Join-Path $temporaryParent "json-codr-verifier-$runId-outside"
$receiptRoot = Join-Path $env:LOCALAPPDATA 'JSON_CODR\verification-receipts'
if (-not $ReceiptPath) {
  $ReceiptPath = Join-Path $receiptRoot "coding-workflow-$runId.json"
}
$ReceiptPath = [IO.Path]::GetFullPath($ReceiptPath)

$receipt = [ordered]@{
  schema_version = '1'
  verifier = 'JSON_CODR disposable coding workflow'
  run_id = $runId
  status = 'running'
  revision = $null
  model = $null
  model_digest = $null
  project_fingerprint = $null
  steps = @()
  negative_checks = @()
  commit = $null
  disposed = $false
  completed_at = $null
}
$token = $null
$escapeLink = $null
$failure = $null

function Get-Sha256Text([string]$Value) {
  $bytes = [Text.Encoding]::UTF8.GetBytes($Value)
  $hash = [Security.Cryptography.SHA256]::Create()
  try { return 'sha256:' + ([BitConverter]::ToString($hash.ComputeHash($bytes))).Replace('-', '').ToLowerInvariant() }
  finally { $hash.Dispose() }
}

function Get-Sha256File([string]$Path) {
  $stream = [IO.File]::OpenRead($Path)
  $hash = [Security.Cryptography.SHA256]::Create()
  try { return 'sha256:' + ([BitConverter]::ToString($hash.ComputeHash($stream))).Replace('-', '').ToLowerInvariant() }
  finally { $hash.Dispose(); $stream.Dispose() }
}

function Assert-LoopbackOrigin([string]$Value) {
  $uri = [Uri]$Value
  if ($uri.Scheme -notin @('http', 'https') -or $uri.AbsolutePath -ne '/' -or $uri.Query -or $uri.Fragment) {
    throw 'ServerOrigin must be an HTTP(S) origin without a path, query, or fragment'
  }
  $hostName = $uri.DnsSafeHost.Trim('[', ']').ToLowerInvariant()
  if ($hostName -notin @('localhost', '127.0.0.1', '::1')) {
    throw 'ServerOrigin must use a direct loopback host'
  }
  return $uri.GetLeftPart([UriPartial]::Authority).TrimEnd('/')
}

function Invoke-JsonApi([string]$Method, [string]$Path, $Body = $null) {
  $parameters = @{
    Uri = "$script:apiOrigin$Path"
    Method = $Method
    Headers = @{ Authorization = "Bearer $script:token" }
    UseBasicParsing = $true
    MaximumRedirection = 0
    TimeoutSec = 60
  }
  if ($null -ne $Body) {
    $parameters.ContentType = 'application/json'
    $parameters.Body = ($Body | ConvertTo-Json -Depth 40 -Compress)
  }
  try {
    $response = Invoke-WebRequest @parameters
  } catch {
    $detail = $_.Exception.Message
    if ($_.ErrorDetails -and $_.ErrorDetails.Message) { $detail = $_.ErrorDetails.Message }
    throw "Authenticated API $Method $Path failed: $detail"
  }
  if (-not $response.Content) { return $null }
  return $response.Content | ConvertFrom-Json
}

function Invoke-Capability(
  [string]$CapabilityId,
  [string]$Operation,
  [string]$TargetPath,
  [hashtable]$Arguments,
  [switch]$ExpectFailure
) {
  $nonce = [Guid]::NewGuid().ToString('N')
  $payload = [ordered]@{
    capability_id = $CapabilityId
    operation = $Operation
    project_root = $script:projectRoot
    mode = 'native'
    arguments = $Arguments
  }
  if ($TargetPath) { $payload.target_path = $TargetPath }
  $command = [ordered]@{
    schema_version = '1'
    command_id = "verify-$nonce"
    task_id = "verify-task-$nonce"
    thread_id = "verify-thread-$script:runId"
    project_id = "verify-project-$script:runId"
    command_type = 'capability.execute'
    payload = $payload
  }
  $record = Invoke-JsonApi 'POST' '/api/tasks' $command
  $permission = @($record.events | Where-Object { $_.event_type -eq 'task.permission_required' } | Select-Object -Last 1)
  if ($permission.Count -eq 1) {
    $proposalId = [string]$permission[0].payload.proposal_id
    if (-not $proposalId) { throw "$CapabilityId did not return an exact approval proposal" }
    $record = Invoke-JsonApi 'POST' "/api/tasks/$($record.task_id)/approve" @{
      scope = 'project'
      proposal_id = $proposalId
    }
  }
  if ($ExpectFailure) {
    if ($record.status -ne 'failed') { throw "$CapabilityId unexpectedly succeeded" }
  } elseif ($record.status -ne 'completed') {
    throw "$CapabilityId failed with status $($record.status)"
  }
  return $record
}

function Get-CheckpointId($Record) {
  $event = @($Record.events | Where-Object { $_.event_type -eq 'checkpoint.created' } | Select-Object -Last 1)
  if ($event.Count -ne 1 -or -not $event[0].payload.checkpoint_id) {
    throw 'Mutation did not return a checkpoint'
  }
  return [string]$event[0].payload.checkpoint_id
}

function Add-Step([string]$Name, $Record, [hashtable]$Evidence = @{}) {
  $eventDigests = @($Record.events | ForEach-Object { $_.event_digest } | Where-Object { $_ })
  $script:receipt.steps += [ordered]@{
    name = $Name
    task_id = $Record.task_id
    status = $Record.status
    final_event_digest = if ($eventDigests.Count) { $eventDigests[-1] } else { $null }
    evidence = $Evidence
  }
}

function Invoke-SafeGit([string[]]$Arguments) {
  $previous = Get-Location
  try {
    Set-Location -LiteralPath $script:projectRoot
    $hookSink = if ($env:OS -eq 'Windows_NT') { 'NUL' } else { '/dev/null' }
    $output = & git -c "core.hooksPath=$hookSink" @Arguments 2>&1
    if ($LASTEXITCODE -ne 0) { throw (($output | Out-String).Trim()) }
    return (($output | Out-String).Trim())
  } finally {
    Set-Location $previous
  }
}

try {
  $apiOrigin = Assert-LoopbackOrigin $ServerOrigin
  $health = Invoke-RestMethod -Uri "$apiOrigin/api/health" -MaximumRedirection 0 -TimeoutSec 10
  if ($health.status -ne 'ready') { throw "Live service is not ready: $($health.status)" }
  $receipt.revision = [string]$health.revision

  $authOutput = (& $Python -m web_app.core.cli auth status 2>&1 | Out-String).Trim()
  if ($LASTEXITCODE -ne 0) { throw "Authenticated CLI is required: $authOutput" }
  $token = (& $Python -c "from pathlib import Path; from web_app.core.cli_identity import DpapiTokenStore; import sys; sys.stdout.write(DpapiTokenStore(Path.home()/'.json_codr'/'credentials'/'cli.dpapi').load()['token'])" | Out-String).Trim()
  if ($LASTEXITCODE -ne 0 -or -not $token) { throw 'Unable to load the authenticated CLI credential' }

  New-Item -ItemType Directory -Path $projectRoot -Force | Out-Null
  New-Item -ItemType Directory -Path $outsideRoot -Force | Out-Null

  $policy = Get-Content -Raw (Join-Path $sourceRoot 'config\bootstrap-models.json') | ConvertFrom-Json
  $ollama = Invoke-RestMethod -Uri 'http://127.0.0.1:11434/api/tags' -MaximumRedirection 0 -TimeoutSec 10
  $selected = $null
  foreach ($candidate in $policy.models) {
    $installed = @($ollama.models | Where-Object { $_.name -eq $candidate.name } | Select-Object -First 1)
    if ($installed.Count -ne 1) { continue }
    $actualDigest = 'sha256:' + ([string]$installed[0].digest).ToLowerInvariant().Replace('sha256:', '')
    if ($actualDigest -ne $candidate.digest) { continue }
    $cliResultText = (& $Python -m web_app.core.cli run 'Return exactly JSON_CODR_CODING_WORKFLOW_OK.' --project $projectRoot --model $candidate.name --output json --url $apiOrigin 2>&1 | Out-String).Trim()
    if ($LASTEXITCODE -ne 0) { continue }
    try { $cliResult = $cliResultText | ConvertFrom-Json } catch { continue }
    if ($cliResult.status -eq 'completed') {
      $selected = $candidate
      break
    }
  }
  if ($null -eq $selected) { throw 'No digest-reviewed coding model completed the authenticated CLI probe' }
  $receipt.model = [string]$selected.name
  $receipt.model_digest = [string]$selected.digest

  Invoke-SafeGit @('init', '-b', 'main') | Out-Null
  Invoke-SafeGit @('config', 'user.name', 'JSON CODR Verifier') | Out-Null
  Invoke-SafeGit @('config', 'user.email', 'verifier@example.invalid') | Out-Null
  Invoke-SafeGit @('remote', 'add', 'origin', 'https://github.com/json-codr-verifier/disposable.git') | Out-Null
  [IO.File]::WriteAllText((Join-Path $projectRoot 'README.md'), "disposable verification`n", [Text.UTF8Encoding]::new($false))
  Invoke-SafeGit @('add', '--', 'README.md') | Out-Null
  Invoke-SafeGit @('commit', '-m', 'Initial disposable repository') | Out-Null

  $escapeLink = Join-Path $projectRoot 'escape-link'
  New-Item -ItemType Junction -Path $escapeLink -Target $outsideRoot | Out-Null
  $escape = Invoke-Capability 'native.write' 'bounded_edit' 'escape-link/owned.txt' @{ content = "escaped`n" } -ExpectFailure
  if (Test-Path (Join-Path $outsideRoot 'owned.txt')) { throw 'Project mutation escaped through a junction' }
  $receipt.negative_checks += [ordered]@{ name = 'junction_escape'; status = 'rejected'; task_id = $escape.task_id }
  Remove-Item -LiteralPath $escapeLink -Force
  $escapeLink = $null

  $calculator = @"
def add(left, right):
    return left - right
"@
  $created = Invoke-Capability 'native.write' 'bounded_edit' 'calculator.py' @{ content = $calculator }
  Add-Step 'create' $created @{ path = 'calculator.py'; checkpoint_id = (Get-CheckpointId $created) }

  $tests = @"
import unittest
from calculator import add


class CalculatorTests(unittest.TestCase):
    def test_add(self):
        self.assertEqual(add(2, 3), 5)


if __name__ == '__main__':
    unittest.main()
"@
  $testCreated = Invoke-Capability 'native.write' 'bounded_edit' 'test_calculator.py' @{ content = $tests }
  Add-Step 'create_test' $testCreated @{ path = 'test_calculator.py'; checkpoint_id = (Get-CheckpointId $testCreated) }

  $edit = Invoke-Capability 'native.edit' 'bounded_edit' 'calculator.py' @{
    diff_hunk = "@@ -1,2 +1,2 @@`n def add(left, right):`n-    return left - right`n+    return left + right"
  }
  Add-Step 'edit' $edit @{ path = 'calculator.py'; checkpoint_id = (Get-CheckpointId $edit) }

  $previous = Get-Location
  try {
    Set-Location -LiteralPath $projectRoot
    $testOutput = (& $Python -m unittest -v 2>&1 | Out-String).Trim()
    if ($LASTEXITCODE -ne 0) { throw "Disposable project tests failed: $testOutput" }
  } finally { Set-Location $previous }
  $receipt.steps += [ordered]@{ name = 'test'; status = 'completed'; evidence = @{ output_digest = (Get-Sha256Text $testOutput) } }

  $craftedName = '--upload-pack=owned path.txt'
  $crafted = Invoke-Capability 'native.write' 'bounded_edit' $craftedName @{ content = "filename is data`n" }
  Add-Step 'crafted_filename' $crafted @{ path = $craftedName; checkpoint_id = (Get-CheckpointId $crafted) }

  Invoke-SafeGit @('--literal-pathspecs', 'add', '--', 'calculator.py', 'test_calculator.py', $craftedName) | Out-Null
  $diffText = Invoke-SafeGit @('diff', '--cached', '--binary', '--', 'calculator.py', 'test_calculator.py', $craftedName)
  if (-not $diffText) { throw 'Disposable repository did not produce a Git diff' }
  $receipt.steps += [ordered]@{ name = 'diff'; status = 'completed'; evidence = @{ digest = (Get-Sha256Text $diffText) } }

  $hookSentinel = Join-Path $outsideRoot 'hostile-hook-ran.txt'
  $hookPath = Join-Path $projectRoot '.git\hooks\pre-commit'
  $hookTarget = $hookSentinel.Replace('\', '/')
  [IO.File]::WriteAllText($hookPath, "#!/bin/sh`nprintf escaped > `"$hookTarget`"`n", [Text.UTF8Encoding]::new($false))

  $gitRoute = 'local-adapter'
  if ($authOutput -match 'git\.edit' -and $authOutput -match 'git\.commit') {
    Invoke-JsonApi 'POST' '/api/github/local/stage' @{ confirmed = $true; project_root = $projectRoot; paths = @('calculator.py', 'test_calculator.py', $craftedName) } | Out-Null
    $committed = Invoke-JsonApi 'POST' '/api/github/local/commit' @{ confirmed = $true; project_root = $projectRoot; message = 'Verify disposable coding workflow' }
    $commitSha = [string]$committed.commit
    $gitRoute = 'authenticated-api'
  } else {
    $adapterCode = "import sys; from web_app.github_cli import GitHubCLI; print(GitHubCLI().commit_local_changes(sys.argv[1], sys.argv[2])['commit'])"
    $commitSha = (& $Python -c $adapterCode $projectRoot 'Verify disposable coding workflow' 2>&1 | Out-String).Trim()
    if ($LASTEXITCODE -ne 0 -or $commitSha -notmatch '^[0-9a-f]{40,64}$') { throw "Git adapter commit failed: $commitSha" }
  }
  if (Test-Path $hookSentinel) { throw 'Repository-controlled Git hook executed during verified commit' }
  $receipt.negative_checks += [ordered]@{ name = 'hostile_git_hook'; status = 'blocked' }
  $receipt.commit = [ordered]@{ sha = $commitSha; route = $gitRoute; tree = (Invoke-SafeGit @('rev-parse', 'HEAD^{tree}')) }

  $environmentCode = @"
import asyncio, pathlib, sys
from web_app.core.command_runtime import CommandPolicy, CommandRuntime
async def check():
    policy = CommandPolicy(argv=(sys.executable, '-c', "import pathlib; pathlib.Path('environment-escaped.txt').write_text('owned')"), cwd='.', environment={'AWS_SECRET_ACCESS_KEY':'owned'})
    try:
        await CommandRuntime().run_interactive_admin(policy, project_root=sys.argv[1], administrator_scopes=('terminal.write',))
    except ValueError as error:
        if 'environment key' not in str(error):
            raise
        return
    raise RuntimeError('environment injection was accepted')
asyncio.run(check())
"@
  & $Python -c $environmentCode $projectRoot
  if ($LASTEXITCODE -ne 0 -or (Test-Path (Join-Path $projectRoot 'environment-escaped.txt'))) { throw 'Environment injection boundary failed' }
  $receipt.negative_checks += [ordered]@{ name = 'environment_injection'; status = 'rejected' }

  $undo = Invoke-Capability 'native.write' 'bounded_edit' 'undo.txt' @{ content = "approved temporary state`n" }
  $undoCheckpoint = Get-CheckpointId $undo
  [IO.File]::WriteAllText((Join-Path $projectRoot 'undo.txt'), "drifted state`n", [Text.UTF8Encoding]::new($false))
  $mismatch = Invoke-Capability 'checkpoint.restore' 'destructive' '' @{ checkpoint_id = $undoCheckpoint } -ExpectFailure
  if ((Get-Content -Raw (Join-Path $projectRoot 'undo.txt')) -ne "drifted state`n") { throw 'Rollback mismatch changed the target' }
  $receipt.negative_checks += [ordered]@{ name = 'rollback_mismatch'; status = 'rejected'; task_id = $mismatch.task_id }
  [IO.File]::WriteAllText((Join-Path $projectRoot 'undo.txt'), "approved temporary state`n", [Text.UTF8Encoding]::new($false))
  $restored = Invoke-Capability 'checkpoint.restore' 'destructive' '' @{ checkpoint_id = $undoCheckpoint }
  if (Test-Path (Join-Path $projectRoot 'undo.txt')) { throw 'Approved undo did not restore the absent-file state' }
  Add-Step 'undo' $restored @{ checkpoint_id = $undoCheckpoint }

  if ((Invoke-SafeGit @('status', '--porcelain')) -ne '') { throw 'Disposable repository is dirty after commit and undo' }
  $receipt.project_fingerprint = Get-Sha256Text ((Invoke-SafeGit @('ls-tree', '-r', '--full-tree', 'HEAD')))
  $receipt.status = 'passed'
} catch {
  $failure = $_
  $receipt.status = 'failed'
  $receipt.error = $_.Exception.Message
} finally {
  if ($escapeLink -and (Test-Path -LiteralPath $escapeLink)) {
    Remove-Item -LiteralPath $escapeLink -Force -ErrorAction SilentlyContinue
  }
  foreach ($target in @($projectRoot, $outsideRoot)) {
    $resolved = [IO.Path]::GetFullPath($target)
    $name = [IO.Path]::GetFileName($resolved)
    $parent = [IO.Path]::GetDirectoryName($resolved).TrimEnd('\')
    if ($parent -ne $temporaryParent -or $name -notlike "json-codr-verifier-$runId*") {
      throw "Refusing to remove unexpected verifier path: $resolved"
    }
    if (Test-Path -LiteralPath $resolved) { Remove-Item -LiteralPath $resolved -Recurse -Force }
  }
  $receipt.disposed = -not (Test-Path -LiteralPath $projectRoot) -and -not (Test-Path -LiteralPath $outsideRoot)
  $receipt.completed_at = [DateTimeOffset]::UtcNow.ToString('o')
  $receiptDirectory = Split-Path -Parent $ReceiptPath
  New-Item -ItemType Directory -Path $receiptDirectory -Force | Out-Null
  $receiptJson = $receipt | ConvertTo-Json -Depth 40
  [IO.File]::WriteAllText($ReceiptPath, $receiptJson, [Text.UTF8Encoding]::new($false))
}

if ($failure) {
  Write-Error "Disposable coding verification failed. Receipt: $ReceiptPath. $($failure.Exception.Message)"
  exit 1
}

$receipt | ConvertTo-Json -Depth 40 -Compress
exit 0
