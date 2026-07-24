$ErrorActionPreference = 'Stop'
$scriptPath = Join-Path $PSScriptRoot '..\scripts\New-SourceSnapshot.ps1'
$script = Get-Content -Raw -Encoding UTF8 -LiteralPath $scriptPath

function New-SnapshotFixture {
  param([Parameter(Mandatory = $true)][string]$Sandbox)
  $repo = Join-Path $Sandbox 'repo'
  $scripts = Join-Path $repo 'scripts'
  New-Item -ItemType Directory -Path $scripts -Force | Out-Null
  Copy-Item -LiteralPath $scriptPath -Destination (Join-Path $scripts 'New-SourceSnapshot.ps1')
  Set-Content -LiteralPath (Join-Path $repo 'main.js') -Value 'fixture source' -Encoding UTF8
  return $repo
}

function Invoke-SnapshotExpectFailure {
  param(
    [Parameter(Mandatory = $true)][string]$FixtureScript,
    [Parameter(Mandatory = $true)][string]$Destination
  )
  $previousErrorActionPreference = $ErrorActionPreference
  try {
    $ErrorActionPreference = 'Continue'
    $output = @(& powershell -NoProfile -ExecutionPolicy Bypass -File $FixtureScript -Destination $Destination 2>&1)
    $exitCode = $LASTEXITCODE
  } finally {
    $ErrorActionPreference = $previousErrorActionPreference
  }
  if ($exitCode -eq 0) { throw "Expected snapshot command to reject destination: $Destination`n$($output -join "`n")" }
}

foreach ($required in @(
  "'node_modules'", "'release'", "'dist'", "'runtime-release'",
  "'runtime/workspaces'", 'SOURCE_MANIFEST.json', 'SOURCE_SHA256SUMS.txt',
  'Unsafe source snapshot destination', 'Get-FileHash'
)) {
  if ($script -notmatch [regex]::Escape($required)) { throw "Source snapshot contract missing: $required" }
}
if ($script -notmatch 'dirty = \[bool\]') { throw 'Source snapshot must record dirty worktree state' }
if ($script -notmatch 'StartsWith\(\$Root') { throw 'Source snapshot must reject destinations inside the source tree' }

$safetySandbox = Join-Path ([IO.Path]::GetTempPath()) ("vibe-source-snapshot-safety-" + [guid]::NewGuid().ToString('N'))
try {
  $repo = New-SnapshotFixture -Sandbox $safetySandbox
  $fixtureScript = Join-Path $repo 'scripts\New-SourceSnapshot.ps1'
  Invoke-SnapshotExpectFailure -FixtureScript $fixtureScript -Destination $safetySandbox
  Invoke-SnapshotExpectFailure -FixtureScript $fixtureScript -Destination (Join-Path $repo 'nested-destination')

  $destinationLink = Join-Path $safetySandbox 'destination-link'
  try {
    New-Item -ItemType Junction -Path $destinationLink -Target $repo -ErrorAction Stop | Out-Null
    Invoke-SnapshotExpectFailure -FixtureScript $fixtureScript -Destination $destinationLink
  } catch [System.UnauthorizedAccessException] {
    Write-Warning 'Skipping junction destination assertion because this host cannot create junctions'
  }
} finally {
  if (Test-Path -LiteralPath $safetySandbox) { Remove-Item -LiteralPath $safetySandbox -Recurse -Force }
}

$destination = Join-Path ([IO.Path]::GetTempPath()) ("vibe-source-snapshot-smoke-" + [guid]::NewGuid().ToString('N'))
$smokeSandbox = Join-Path ([IO.Path]::GetTempPath()) ("vibe-source-snapshot-repo-" + [guid]::NewGuid().ToString('N'))
try {
  $smokeRepo = New-SnapshotFixture -Sandbox $smokeSandbox
  New-Item -ItemType Directory -Path (Join-Path $smokeRepo 'node_modules\ignored') -Force | Out-Null
  Set-Content -LiteralPath (Join-Path $smokeRepo 'node_modules\ignored\secret.js') -Value 'excluded' -Encoding UTF8
  New-Item -ItemType Directory -Path (Join-Path $smokeRepo 'backend') -Force | Out-Null
  Set-Content -LiteralPath (Join-Path $smokeRepo 'backend\main.py') -Value 'print("included")' -Encoding UTF8
  $result = & powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $smokeRepo 'scripts\New-SourceSnapshot.ps1') -Destination $destination | ConvertFrom-Json
  if (!$result.ok -or $result.files -le 0 -or !(Test-Path -LiteralPath (Join-Path $destination 'SOURCE_MANIFEST.json'))) {
    throw 'Source snapshot did not produce a valid result and manifest'
  }
  $manifest = Get-Content -Raw -Encoding UTF8 -LiteralPath (Join-Path $destination 'SOURCE_MANIFEST.json') | ConvertFrom-Json
  if ($manifest.file_count -ne $manifest.files.Count -or $manifest.bytes -le 0) { throw 'Manifest file count or byte total is invalid' }
  if ($manifest.files.path | Where-Object { $_ -match '(^|/)node_modules(/|$)|(^|/)release(/|$)|(^|/)runtime/workspaces(/|$)' }) {
    throw 'Snapshot contains excluded generated content'
  }
  if (!(Test-Path -LiteralPath (Join-Path $destination 'main.js'))) { throw 'Snapshot is missing application source' }
  if (!(Test-Path -LiteralPath (Join-Path $destination 'backend\main.py'))) { throw 'Snapshot is missing nested application source' }
} finally {
  if (Test-Path -LiteralPath $destination) { Remove-Item -LiteralPath $destination -Recurse -Force }
  if (Test-Path -LiteralPath $smokeSandbox) { Remove-Item -LiteralPath $smokeSandbox -Recurse -Force }
}
Write-Output 'source snapshot contract and smoke test OK'
