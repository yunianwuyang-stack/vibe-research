[CmdletBinding()]
param(
  [switch]$SkipPackage,
  [switch]$LocalValidationOnly
)
$ErrorActionPreference = 'Stop'
# Prefer the verified mirror; callers may override only with an HTTPS mirror.
if (!$env:ELECTRON_MIRROR) { $env:ELECTRON_MIRROR = 'https://npmmirror.com/mirrors/electron/' }
if (!$env:ELECTRON_MIRROR.StartsWith('https://')) { throw 'ELECTRON_MIRROR must use HTTPS' }
$Root = Split-Path -Parent $PSScriptRoot
$RootLock = Join-Path $Root 'package-lock.json'
if (!(Test-Path -LiteralPath $RootLock -PathType Leaf)) { throw 'package-lock.json is required for reproducible builds' }

Push-Location $Root
try {
  npm.cmd ci
  if ($LASTEXITCODE -ne 0) { throw "root npm ci failed with exit code $LASTEXITCODE" }
} finally { Pop-Location }

if (!$SkipPackage) {
  $releaseRoot = Join-Path $Root 'release'
  if (Test-Path -LiteralPath $releaseRoot) { Remove-Item -LiteralPath $releaseRoot -Recurse -Force }
}
$runtimeStageArguments = @{}
if ($LocalValidationOnly) { $runtimeStageArguments.LocalValidationOnly = $true }
& (Join-Path $PSScriptRoot 'New-MinimalRuntime.ps1') @runtimeStageArguments | Write-Host
$RuntimeStageManifestPath = Join-Path $Root 'runtime-release\manifest.json'
$RuntimeStageSummaryPath = Join-Path $Root 'runtime-release\manifest.summary.json'
if (!(Test-Path -LiteralPath $RuntimeStageManifestPath -PathType Leaf)) {
  throw 'Runtime staging did not produce runtime-release/manifest.json'
}
if (!(Test-Path -LiteralPath $RuntimeStageSummaryPath -PathType Leaf)) {
  throw 'Runtime staging did not produce runtime-release/manifest.summary.json'
}
$RuntimeStageManifest = Get-Content $RuntimeStageSummaryPath -Raw -Encoding UTF8 | ConvertFrom-Json

function Assert-ExternalClaudeAdapterContract {
  param(
    [Parameter(Mandatory = $true)]$Manifest,
    [Parameter(Mandatory = $true)][string]$Context
  )

  $adapter = $Manifest.external_adapters.claude
  if ($null -eq $adapter) {
    throw "$Context is missing manifest.external_adapters.claude"
  }
  if (
    $null -eq $adapter.PSObject.Properties['bundled'] -or
    ($adapter.bundled -isnot [bool]) -or
    $adapter.bundled
  ) {
    throw "$Context must declare manifest.external_adapters.claude.bundled=false as a boolean"
  }
  if (
    $null -eq $adapter.PSObject.Properties['required'] -or
    ($adapter.required -isnot [bool]) -or
    $adapter.required
  ) {
    throw "$Context must declare manifest.external_adapters.claude.required=false as a boolean"
  }
}

function Assert-NoBundledClaudePayload {
  param(
    [Parameter(Mandatory = $true)][string]$RuntimeRoot,
    [Parameter(Mandatory = $true)][string]$Context
  )

  if (!(Test-Path -LiteralPath $RuntimeRoot -PathType Container)) {
    throw "$Context runtime directory is missing: $RuntimeRoot"
  }
  $resolvedRuntime = (Resolve-Path -LiteralPath $RuntimeRoot).Path.TrimEnd([char[]]'\/')
  $violations = @(Get-ChildItem -LiteralPath $resolvedRuntime -Recurse -Force -ErrorAction Stop | Where-Object {
    $relative = $_.FullName.Substring($resolvedRuntime.Length).TrimStart([char[]]'\/')
    $_.Name -in @('claude', 'claude.cmd', 'claude.ps1', 'claude.bat', 'claude.exe') -or
    $relative -match '(?i)(^|[\\/])@anthropic-ai[\\/]claude-code(?:-win32-x64)?(?:$|[\\/])' -or
    $relative -match '(?i)(^|[\\/])agents[\\/]claude(?:$|[\\/])' -or
    $relative -match '(?i)(^|[\\/])licenses?[\\/][^\\/]*claude[^\\/]*(?:$|[\\/])'
  } | Select-Object -First 20)
  if ($violations.Count -gt 0) {
    $paths = @($violations | ForEach-Object { $_.FullName }) -join ', '
    throw "$Context contains forbidden bundled Claude payloads: $paths"
  }
}

function Assert-ReleasePayloadPolicy {
  param([Parameter(Mandatory = $true)][string]$UnpackedRoot)

  $resourcesRoot = Join-Path $UnpackedRoot 'resources'
  $asar = Join-Path $resourcesRoot 'app.asar'
  $unpackedApp = Join-Path $resourcesRoot 'app.asar.unpacked'
  if (!(Test-Path -LiteralPath $asar -PathType Leaf)) { throw "Packaged app.asar is missing: $asar" }
  if (!(Test-Path -LiteralPath (Join-Path $unpackedApp 'backend') -PathType Container)) {
    throw "Packaged executable backend is missing: $unpackedApp"
  }

  $appRoot = Join-Path $resourcesRoot 'app.asar.unpacked'
  $forbidden = @(Get-ChildItem -LiteralPath $appRoot -Recurse -Force -ErrorAction Stop | Where-Object {
    $relative = $_.FullName.Substring($appRoot.Length).TrimStart([char[]]'\/').Replace('\','/')
    $relative -match '(?i)(^|/)(tests?|__tests__|evals|__pycache__|\.pytest_cache|\.git|\.github|\.claude)(/|$)' -or
    (!$_.PSIsContainer -and ($_.Extension -in @('.map','.pyc','.pyo','.ts','.tsx') -or $_.Name -match '^(\.env.*|builder-debug\.yml)$'))
  } | Select-Object -First 30)
  if ($forbidden.Count -gt 0) {
    throw "Packaged payload contains forbidden development artifacts: $(@($forbidden.FullName) -join ', ')"
  }

  $looseMain = Join-Path $resourcesRoot 'app\main.js'
  $looseBackend = Join-Path $resourcesRoot 'app\backend'
  if ((Test-Path -LiteralPath $looseMain) -or (Test-Path -LiteralPath $looseBackend)) {
    throw 'Packaged payload exposes the application as loose resources/app source'
  }
  Write-Host "Packaged payload policy verified: ASAR enabled and development artifacts absent ($UnpackedRoot)"
}

function Assert-PackagedRuntimeAgentPolicy {
  param([Parameter(Mandatory = $true)][string]$UnpackedRoot)

  $runtimeRoot = Join-Path $UnpackedRoot 'resources\runtime'
  Assert-NoBundledClaudePayload -RuntimeRoot $runtimeRoot -Context 'Packaged runtime'

  $summaryPath = Join-Path $runtimeRoot 'manifest.summary.json'
  if (!(Test-Path -LiteralPath $summaryPath -PathType Leaf)) {
    throw "Packaged runtime summary is missing: $summaryPath"
  }
  $summary = Get-Content -LiteralPath $summaryPath -Raw -Encoding UTF8 | ConvertFrom-Json
  Assert-ExternalClaudeAdapterContract -Manifest $summary -Context 'Packaged runtime summary'
  if ($null -ne $summary.agent_clis.claude -or $null -ne $summary.capabilities.claude) {
    throw 'Packaged runtime manifest incorrectly declares Claude as a shipped capability or Agent CLI'
  }

  $agentManifestPath = Join-Path $runtimeRoot 'agent-cli-manifest.json'
  if (!(Test-Path -LiteralPath $agentManifestPath -PathType Leaf)) {
    throw "Packaged Agent CLI manifest is missing: $agentManifestPath"
  }
  $agentManifest = Get-Content -LiteralPath $agentManifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
  Assert-ExternalClaudeAdapterContract -Manifest $agentManifest -Context 'Packaged Agent CLI manifest'
  if ($null -ne $agentManifest.adapters.claude) {
    throw 'Packaged Agent CLI manifest incorrectly declares Claude as a bundled adapter'
  }

  $codexRelativePath = [string]$summary.agent_clis.codex.executable
  if (!$codexRelativePath -or [IO.Path]::IsPathRooted($codexRelativePath) -or $codexRelativePath -match '(^|[\\/])\.\.([\\/]|$)') {
    throw 'Packaged runtime summary contains an invalid Codex executable path'
  }
  $codexPath = [IO.Path]::GetFullPath((Join-Path $runtimeRoot $codexRelativePath))
  $resolvedRuntime = (Resolve-Path -LiteralPath $runtimeRoot).Path.TrimEnd([char[]]'\/')
  if (
    !$codexPath.StartsWith($resolvedRuntime + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase) -or
    !(Test-Path -LiteralPath $codexPath -PathType Leaf)
  ) {
    throw "Packaged Codex executable is missing or escapes the runtime root: $codexPath"
  }
  Write-Host "Packaged runtime Agent CLI policy verified: Codex bundled, Claude external-only ($runtimeRoot)"
}

function Restore-MissingRuntimeStageEntries {
  param([Parameter(Mandatory = $true)][string]$PackagedRuntimeRoot)
  $stageRoot = Join-Path $Root 'runtime-release'
  foreach ($sourceEntry in Get-ChildItem -LiteralPath $PackagedRuntimeRoot -Force) {
    $destination = Join-Path $stageRoot $sourceEntry.Name
    if (!(Test-Path -LiteralPath $destination)) {
      Copy-Item -LiteralPath $sourceEntry.FullName -Destination $destination -Recurse -Force
    }
  }
  foreach ($relative in @('manifest.json','manifest.summary.json','agent-cli-manifest.json','python\python.exe')) {
    $stageFile = Join-Path $stageRoot $relative
    $packagedFile = Join-Path $PackagedRuntimeRoot $relative
    if (!(Test-Path -LiteralPath $stageFile -PathType Leaf) -or (Get-FileHash -LiteralPath $stageFile).Hash -ne (Get-FileHash -LiteralPath $packagedFile).Hash) {
      throw "Runtime staging recovery mismatch: $relative"
    }
  }
  Assert-NoBundledClaudePayload -RuntimeRoot $stageRoot -Context 'Recovered runtime staging'
}

Assert-ExternalClaudeAdapterContract -Manifest $RuntimeStageManifest -Context 'Runtime staging manifest'
if ($null -ne $RuntimeStageManifest.agent_clis.claude -or $null -ne $RuntimeStageManifest.capabilities.claude) {
  throw 'Runtime staging manifest incorrectly declares Claude as a shipped capability or Agent CLI'
}
Assert-NoBundledClaudePayload -RuntimeRoot (Join-Path $Root 'runtime-release') -Context 'Runtime staging'

$requiredCapabilities = @('python','node','codex','ripgrep','git','bash','pandoc','drawio','xelatex','pdflatex','latexmk','biber')
foreach ($capability in $requiredCapabilities) {
  if (!$RuntimeStageManifest.capabilities.$capability.sha256) {
    throw "Runtime staging manifest is missing required capability: $capability"
  }
}
if (!$RuntimeStageManifest.release_eligible -and !$LocalValidationOnly) {
  throw "Runtime is not eligible for redistribution: $($RuntimeStageManifest.release_blockers -join ', ')"
}
if ($LocalValidationOnly -and $RuntimeStageManifest.build_purpose -ne 'local_validation_only') {
  throw 'Runtime staging did not record the requested local-validation-only purpose'
}
foreach ($agentName in @('codex')) {
  $agent = $RuntimeStageManifest.agent_clis.$agentName
  if (!$agent -or !$agent.sha256 -or !$agent.reported_version -or !$agent.license -or !$agent.license_files) {
    throw "Runtime staging manifest is missing attested Agent CLI: $agentName"
  }
}
$Frontend = Join-Path $Root 'frontend'
$Lock = Join-Path $Frontend 'package-lock.json'
if (!(Test-Path $Lock)) { throw 'frontend/package-lock.json is required for reproducible builds' }
Push-Location $Frontend
try {
  npm.cmd ci
  if ($LASTEXITCODE -ne 0) { throw "npm ci failed with exit code $LASTEXITCODE" }
  npm.cmd run build
  if ($LASTEXITCODE -ne 0) { throw "frontend build failed with exit code $LASTEXITCODE" }
} finally { Pop-Location }
$manifest = [ordered]@{
  schema_version = '1.0'; generated_at_utc = [DateTime]::UtcNow.ToString('o')
  product = 'Vibe Research'; version = (Get-Content (Join-Path $Root 'package.json') -Raw -Encoding UTF8 | ConvertFrom-Json).version
  product_commit = (git -C $Root rev-parse HEAD).Trim()
  product_branch = (git -C $Root branch --show-current).Trim()
  release_eligible = [bool]$RuntimeStageManifest.release_eligible
  release_blockers = @($RuntimeStageManifest.release_blockers)
  build_purpose = $RuntimeStageManifest.build_purpose
  package_lock_sha256 = (Get-FileHash $Lock -Algorithm SHA256).Hash
  backend_requirements_sha256 = (Get-FileHash (Join-Path $Root 'backend\requirements.txt') -Algorithm SHA256).Hash
  runtime = [ordered]@{
    manifest_path = 'runtime/manifest.json'
    manifest_sha256 = (Get-FileHash $RuntimeStageManifestPath -Algorithm SHA256).Hash
    summary_path = 'runtime/manifest.summary.json'
    summary_sha256 = (Get-FileHash $RuntimeStageSummaryPath -Algorithm SHA256).Hash
    schema_version = $RuntimeStageManifest.schema_version
    layout = $RuntimeStageManifest.layout
    release_eligible = [bool]$RuntimeStageManifest.release_eligible
    release_blockers = @($RuntimeStageManifest.release_blockers)
    build_purpose = $RuntimeStageManifest.build_purpose
    files = $RuntimeStageManifest.files
    bytes = $RuntimeStageManifest.bytes
    capabilities = $RuntimeStageManifest.capabilities
    python_packages = $RuntimeStageManifest.python_packages
    agent_clis = $RuntimeStageManifest.agent_clis
    external_adapters = $RuntimeStageManifest.external_adapters
    licenses = $RuntimeStageManifest.licenses
  }
  files = @(Get-ChildItem (Join-Path $Root 'dist') -File -Recurse | ForEach-Object {
    [ordered]@{ path = $_.FullName.Substring($Root.Length + 1).Replace('\','/'); sha256 = (Get-FileHash $_.FullName -Algorithm SHA256).Hash; bytes = $_.Length }
  })
  asar = $true; code_signing = 'blocked_external_certificate_required'
}
$manifestJson = $manifest | ConvertTo-Json -Depth 10
$utf8NoBom = New-Object System.Text.UTF8Encoding($false)
[IO.File]::WriteAllText((Join-Path $Root 'runtime-manifest.json'), $manifestJson, $utf8NoBom)
# Generate dependency inventories even for -SkipPackage preflight builds. The
# final pass below additionally writes checksums for newly built artifacts.
& (Join-Path $PSScriptRoot 'Write-ReleaseMetadata.ps1') -MetadataOnly | Write-Host
if (!$SkipPackage) {
  # Build an unpacked app first, then deterministically apply Vibe Research
  # Windows version resources even when code signing is externally blocked.
  Push-Location $Root
  try {
    npm.cmd exec electron-builder -- --win dir
    if ($LASTEXITCODE -ne 0) { throw "electron-builder dir failed with exit code $LASTEXITCODE" }
  } finally { Pop-Location }
  Assert-PackagedRuntimeAgentPolicy -UnpackedRoot (Join-Path $Root 'release\win-unpacked')
  Assert-ReleasePayloadPolicy -UnpackedRoot (Join-Path $Root 'release\win-unpacked')
  & (Join-Path $PSScriptRoot 'Set-WindowsIdentity.ps1') -Executable (Join-Path $Root 'release\win-unpacked\Vibe Research.exe')
  # Package the already branded/verified directory. A normal `--win nsis`
  # invocation rebuilds win-unpacked and silently restores Electron's version
  # resources inside the installer.
  Push-Location $Root
  try {
    npm.cmd exec electron-builder -- --prepackaged (Join-Path $Root 'release\win-unpacked') --win nsis
    if ($LASTEXITCODE -ne 0) { throw "electron-builder failed with exit code $LASTEXITCODE" }
  } finally { Pop-Location }
  Assert-PackagedRuntimeAgentPolicy -UnpackedRoot (Join-Path $Root 'release\win-unpacked')
  Assert-ReleasePayloadPolicy -UnpackedRoot (Join-Path $Root 'release\win-unpacked')
  $packagedRuntimeRoot = Join-Path $Root 'release\win-unpacked\resources\runtime'
  Restore-MissingRuntimeStageEntries -PackagedRuntimeRoot $packagedRuntimeRoot
  $installer = Get-ChildItem (Join-Path $Root 'release') -File -Filter 'Vibe-Research-*-Setup.exe' -ErrorAction SilentlyContinue | Select-Object -First 1
  if (!$installer) { throw 'No NSIS installer was produced; release build is not successful.' }
  & (Join-Path $PSScriptRoot 'Set-WindowsIdentity.ps1') -Executable (Join-Path $Root 'release\win-unpacked\Vibe Research.exe')
  $manifest.installer = [ordered]@{path=$installer.Name;sha256=(Get-FileHash $installer.FullName).Hash;bytes=$installer.Length;code_signing=(Get-AuthenticodeSignature $installer.FullName).Status.ToString()}
  $manifest.unpacked_executable = [ordered]@{path='release/win-unpacked/Vibe Research.exe';sha256=(Get-FileHash (Join-Path $Root 'release\win-unpacked\Vibe Research.exe')).Hash}
  $manifestJson = $manifest | ConvertTo-Json -Depth 10
  [IO.File]::WriteAllText((Join-Path $Root 'runtime-manifest.json'), $manifestJson, $utf8NoBom)
  & (Join-Path $PSScriptRoot 'Write-ReleaseMetadata.ps1') -RuntimeRoot $packagedRuntimeRoot

  if ($LocalValidationOnly) {
    Write-Warning 'Local validation package created with release_eligible=false; external delivery copy is intentionally disabled.'
    return
  }

  # Keep the externally reviewed delivery directory aligned with the release output.
  $DeliveryName = -join ([char[]]@(0x6700,0x65b0,0x7248,0x6784,0x5efa))
  $Delivery = Join-Path (Split-Path $Root -Parent) $DeliveryName
  if (Test-Path -LiteralPath $Delivery) {
    $resolvedDelivery = (Resolve-Path -LiteralPath $Delivery).Path
    $resolvedParent = (Resolve-Path -LiteralPath (Split-Path $Root -Parent)).Path
    if (!$resolvedDelivery.StartsWith($resolvedParent + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
      throw "Refusing to clean delivery path outside workspace parent: $resolvedDelivery"
    }
    Remove-Item -LiteralPath $resolvedDelivery -Recurse -Force
  }
  New-Item -ItemType Directory -Path $Delivery -Force | Out-Null
  Copy-Item -Path (Join-Path $Root 'release\win-unpacked\*') -Destination $Delivery -Recurse -Force
  Copy-Item -LiteralPath $installer.FullName -Destination (Join-Path $Delivery $installer.Name) -Force
  Assert-PackagedRuntimeAgentPolicy -UnpackedRoot $Delivery
  Assert-ReleasePayloadPolicy -UnpackedRoot $Delivery

  # Keep the externally reviewed delivery directory aligned with the final
  # release metadata as well as the executable payload.
  foreach ($metadata in @('runtime-manifest.json','SBOM.cdx.json','SBOM.spdx.json','LICENSE','THIRD_PARTY_NOTICES.md','README.md')) {
    Copy-Item -LiteralPath (Join-Path $Root $metadata) -Destination (Join-Path $Delivery $metadata) -Force
  }
  Copy-Item -LiteralPath (Join-Path $Root 'release\SHA256SUMS.txt') -Destination (Join-Path $Delivery 'SHA256SUMS.txt') -Force
}
