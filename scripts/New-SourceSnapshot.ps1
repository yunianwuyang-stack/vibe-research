[CmdletBinding()]
param(
  [string]$Destination
)

$ErrorActionPreference = 'Stop'
$Root = (Resolve-Path -LiteralPath (Split-Path -Parent $PSScriptRoot)).Path.TrimEnd([char[]]'\/')
$Parent = (Resolve-Path -LiteralPath (Split-Path -Parent $Root)).Path.TrimEnd([char[]]'\/')
if (!$Destination) {
  $snapshotName = -join ([char[]]@(0x6700,0x65b0,0x7248,0x6e90,0x7801))
  $Destination = Join-Path $Parent $snapshotName
}
$Destination = [IO.Path]::GetFullPath($Destination).TrimEnd([char[]]'\/')
$separator = [IO.Path]::DirectorySeparatorChar

if (
  !$Destination -or
  $Destination -eq [IO.Path]::GetPathRoot($Destination) -or
  $Destination.Equals($Root, [StringComparison]::OrdinalIgnoreCase) -or
  $Destination.StartsWith($Root + $separator, [StringComparison]::OrdinalIgnoreCase) -or
  $Root.StartsWith($Destination + $separator, [StringComparison]::OrdinalIgnoreCase)
) {
  throw "Unsafe source snapshot destination: $Destination"
}

$excludedTopLevel = @(
  '.git', '.venv-dev', '.epipe-test-user-data', 'node_modules', 'release',
  'release-cn', 'release-cn-no-voice', 'dist', 'runtime-release',
  'verification-logs', '_backups'
)
$excludedDirectoryNames = @('__pycache__', '.pytest_cache', '.mypy_cache', '.ruff_cache', 'cache')
$excludedExtensions = @('.pyc', '.pyo', '.log', '.tmp', '.temp')
$excludedRuntimeRelativePrefixes = @(
  'runtime/workspaces', 'runtime/backend', 'runtime/desktop-e2e-appdata',
  'runtime/desktop-e2e-packaged-appdata', 'runtime/run-center-probe-appdata',
  'runtime/real-agent-smoke'
)
$excludedTestRelativePrefixes = @(
  'tests/document_artifacts', 'tests/document_artifacts_retry', 'tests/_docx_smoke'
)

function Get-NormalizedRelativePath {
  param([Parameter(Mandatory = $true)][string]$FullName)
  return $FullName.Substring($Root.Length).TrimStart([char[]]'\/').Replace('\', '/')
}

function Test-ExcludedPath {
  param(
    [Parameter(Mandatory = $true)][string]$RelativePath,
    [Parameter(Mandatory = $true)][bool]$IsDirectory
  )
  $relative = $RelativePath.Replace('\', '/').Trim('/')
  if (!$relative) { return $false }
  $segments = @($relative -split '/')
  if ($segments[0] -in $excludedTopLevel) { return $true }
  if ($segments -contains 'node_modules') { return $true }
  if ($segments | Where-Object { $_ -like '.venv*' }) { return $true }
  if ($segments | Where-Object { $_ -in $excludedDirectoryNames }) { return $true }
  foreach ($prefix in @($excludedRuntimeRelativePrefixes + $excludedTestRelativePrefixes)) {
    if ($relative.Equals($prefix, [StringComparison]::OrdinalIgnoreCase) -or $relative.StartsWith($prefix + '/', [StringComparison]::OrdinalIgnoreCase)) {
      return $true
    }
  }
  if (!$IsDirectory -and ([IO.Path]::GetExtension($relative).ToLowerInvariant() -in $excludedExtensions)) { return $true }
  if (!$IsDirectory -and ([IO.Path]::GetFileName($relative) -match '^(electron_.*acceptance\.(json|png)|builder-debug\.yml)$')) { return $true }
  return $false
}

if (Test-Path -LiteralPath $Destination) {
  $destinationItem = Get-Item -LiteralPath $Destination -Force
  if ($destinationItem.Attributes -band [IO.FileAttributes]::ReparsePoint) {
    throw "Unsafe source snapshot destination reparse point: $Destination"
  }
  $resolvedDestination = $destinationItem.FullName.TrimEnd([char[]]'\/')
  if (
    $resolvedDestination.Equals($Root, [StringComparison]::OrdinalIgnoreCase) -or
    $resolvedDestination.StartsWith($Root + $separator, [StringComparison]::OrdinalIgnoreCase) -or
    $Root.StartsWith($resolvedDestination + $separator, [StringComparison]::OrdinalIgnoreCase)
  ) {
    throw "Refusing to clean unsafe snapshot destination: $resolvedDestination"
  }
  Remove-Item -LiteralPath $resolvedDestination -Recurse -Force
}
New-Item -ItemType Directory -Path $Destination -Force | Out-Null

$sourceFiles = New-Object System.Collections.Generic.List[object]
$pending = New-Object System.Collections.Generic.Stack[string]
$pending.Push($Root)
while ($pending.Count -gt 0) {
  $directory = $pending.Pop()
  foreach ($entry in Get-ChildItem -LiteralPath $directory -Force -ErrorAction Stop) {
    $relative = Get-NormalizedRelativePath -FullName $entry.FullName
    if (Test-ExcludedPath -RelativePath $relative -IsDirectory $entry.PSIsContainer) { continue }
    if ($entry.Attributes -band [IO.FileAttributes]::ReparsePoint) { continue }
    if ($entry.PSIsContainer) {
      $pending.Push($entry.FullName)
      continue
    }
    if ($relative -match '[\r\n]') { throw "Unsupported newline in source path: $relative" }
    $sourceFiles.Add([pscustomobject]@{ Source = $entry.FullName; Relative = $relative })
  }
}

$records = New-Object System.Collections.Generic.List[object]
foreach ($file in $sourceFiles | Sort-Object Relative) {
  $target = Join-Path $Destination $file.Relative.Replace('/', [IO.Path]::DirectorySeparatorChar)
  $targetDirectory = Split-Path -Parent $target
  if (!(Test-Path -LiteralPath $targetDirectory)) { New-Item -ItemType Directory -Path $targetDirectory -Force | Out-Null }
  Copy-Item -LiteralPath $file.Source -Destination $target -Force
  $targetHash = Get-FileHash -LiteralPath $target -Algorithm SHA256
  $targetBytes = (Get-Item -LiteralPath $target -Force).Length
  $records.Add([pscustomobject]@{
    path = $file.Relative
    sha256 = $targetHash.Hash.ToLowerInvariant()
    bytes = [long]$targetBytes
  })
}

function Invoke-VersionText {
  param([string]$Command, [string[]]$Arguments)
  try { return (& $Command @Arguments 2>&1 | Select-Object -First 1).ToString().Trim() } catch { return "unavailable: $($_.Exception.Message)" }
}

$insideWorkTree = (Invoke-VersionText -Command 'git' -Arguments @('-C', $Root, 'rev-parse', '--is-inside-work-tree')) -eq 'true'
if ($insideWorkTree) {
  $commit = Invoke-VersionText -Command 'git' -Arguments @('-C', $Root, 'rev-parse', 'HEAD')
  $branch = Invoke-VersionText -Command 'git' -Arguments @('-C', $Root, 'branch', '--show-current')
  $dirtyLines = @(& git -C $Root status --porcelain=v1 2>$null)
} else {
  $commit = 'unavailable: not a git worktree'
  $branch = ''
  $dirtyLines = @()
}
$manifest = [ordered]@{
  schema_version = '1.0'
  generated_at_utc = [DateTime]::UtcNow.ToString('o')
  source_root = $Root
  snapshot_kind = 'working_tree'
  git = [ordered]@{ commit = $commit; branch = $branch; dirty = [bool]($dirtyLines.Count -gt 0); changed_entries = $dirtyLines.Count }
  tools = [ordered]@{
    powershell = $PSVersionTable.PSVersion.ToString()
    node = Invoke-VersionText -Command 'node' -Arguments @('--version')
    npm = Invoke-VersionText -Command 'npm.cmd' -Arguments @('--version')
    python = Invoke-VersionText -Command (Join-Path $Root 'runtime\python\python.exe') -Arguments @('--version')
  }
  exclusions = [ordered]@{
    top_level = $excludedTopLevel
    directory_names = $excludedDirectoryNames
    extensions = $excludedExtensions
    runtime_prefixes = $excludedRuntimeRelativePrefixes
    test_artifact_prefixes = $excludedTestRelativePrefixes
  }
  files = $records
  file_count = $records.Count
  bytes = [long](($records | ForEach-Object { [long]$_.bytes } | Measure-Object -Sum).Sum)
}
$utf8NoBom = New-Object System.Text.UTF8Encoding($false)
[IO.File]::WriteAllText((Join-Path $Destination 'SOURCE_MANIFEST.json'), ($manifest | ConvertTo-Json -Depth 8), $utf8NoBom)
$checksumLines = @($records | ForEach-Object { "$($_.sha256) *$($_.path)" })
[IO.File]::WriteAllLines((Join-Path $Destination 'SOURCE_SHA256SUMS.txt'), $checksumLines, $utf8NoBom)

[ordered]@{
  ok = $true
  destination = $Destination
  files = $records.Count
  bytes = $manifest.bytes
  git_commit = $commit
  git_dirty = $manifest.git.dirty
} | ConvertTo-Json -Depth 3
