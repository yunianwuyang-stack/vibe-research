[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot
$Package = Get-Content -Raw -Encoding UTF8 -LiteralPath (Join-Path $Root 'package.json') | ConvertFrom-Json
$Unpacked = Join-Path $Root 'release\win-unpacked'
$RuntimeRoot = Join-Path $Unpacked 'resources\runtime'
$Executable = Join-Path $Unpacked 'Vibe Research.exe'
$Installer = Join-Path $Root "release\Vibe-Research-$($Package.version)-Setup.exe"
$SummaryPath = Join-Path $RuntimeRoot 'manifest.summary.json'
$AgentManifestPath = Join-Path $RuntimeRoot 'agent-cli-manifest.json'
foreach ($required in @($Executable, $Installer, $SummaryPath, $AgentManifestPath)) {
  if (!(Test-Path -LiteralPath $required -PathType Leaf)) {
    throw "Cannot finalize an incomplete package: $required"
  }
}

$Summary = Get-Content -Raw -Encoding UTF8 -LiteralPath $SummaryPath | ConvertFrom-Json
$AgentManifest = Get-Content -Raw -Encoding UTF8 -LiteralPath $AgentManifestPath | ConvertFrom-Json
if (!$Summary.release_eligible -or $Summary.build_purpose -ne 'redistributable_release' -or $Summary.release_blockers) {
  throw "Packaged runtime is not release eligible: $($Summary.release_blockers -join ', ')"
}
$ExternalClaude = $Summary.external_adapters.claude
if (
  $null -eq $ExternalClaude -or
  ($ExternalClaude.bundled -isnot [bool]) -or $ExternalClaude.bundled -or
  ($ExternalClaude.required -isnot [bool]) -or $ExternalClaude.required -or
  $null -ne $Summary.agent_clis.claude -or $null -ne $Summary.capabilities.claude -or
  $null -ne $AgentManifest.adapters.claude
) {
  throw 'Packaged runtime does not enforce the external-only Claude adapter contract'
}
$resolvedRuntime = (Resolve-Path -LiteralPath $RuntimeRoot).Path.TrimEnd([char[]]'\/')
$claudePayload = Get-ChildItem -LiteralPath $resolvedRuntime -Recurse -Force | Where-Object {
  $relative = $_.FullName.Substring($resolvedRuntime.Length).TrimStart([char[]]'\/')
  $_.Name -in @('claude','claude.cmd','claude.ps1','claude.bat','claude.exe') -or
  $relative -match '(?i)(^|[\\/])@anthropic-ai[\\/]claude-code(?:-win32-x64)?(?:$|[\\/])' -or
  $relative -match '(?i)(^|[\\/])agents[\\/]claude(?:$|[\\/])'
} | Select-Object -First 1
if ($claudePayload) { throw "Forbidden Claude payload is present: $($claudePayload.FullName)" }

$Codex = $Summary.agent_clis.codex
$CodexPath = [IO.Path]::GetFullPath((Join-Path $RuntimeRoot ([string]$Codex.executable)))
if (
  !$Codex.executable -or
  !$CodexPath.StartsWith($resolvedRuntime + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase) -or
  !(Test-Path -LiteralPath $CodexPath -PathType Leaf) -or
  (Get-FileHash -LiteralPath $CodexPath -Algorithm SHA256).Hash.ToLowerInvariant() -ne ([string]$Codex.sha256).ToLowerInvariant()
) {
  throw 'Bundled Codex executable is missing, outside the runtime, or hash-mismatched'
}

$ManifestPath = Join-Path $Root 'runtime-manifest.json'
$Manifest = Get-Content -Raw -Encoding UTF8 -LiteralPath $ManifestPath | ConvertFrom-Json
$Manifest.release_eligible = $true
$Manifest.release_blockers = @()
$Manifest.build_purpose = 'redistributable_release'
$installerRecord = [ordered]@{
  path = Split-Path -Leaf $Installer
  sha256 = (Get-FileHash -LiteralPath $Installer -Algorithm SHA256).Hash
  bytes = (Get-Item -LiteralPath $Installer).Length
  code_signing = (Get-AuthenticodeSignature -LiteralPath $Installer).Status.ToString()
}
$unpackedRecord = [ordered]@{
  path = 'release/win-unpacked/Vibe Research.exe'
  sha256 = (Get-FileHash -LiteralPath $Executable -Algorithm SHA256).Hash
}
$Manifest | Add-Member -NotePropertyName installer -NotePropertyValue $installerRecord -Force
$Manifest | Add-Member -NotePropertyName unpacked_executable -NotePropertyValue $unpackedRecord -Force
$utf8NoBom = New-Object System.Text.UTF8Encoding($false)
[IO.File]::WriteAllText($ManifestPath, ($Manifest | ConvertTo-Json -Depth 10), $utf8NoBom)

& (Join-Path $PSScriptRoot 'Write-ReleaseMetadata.ps1') -RuntimeRoot $RuntimeRoot | Write-Host
if ($LASTEXITCODE -ne 0) { throw 'Release metadata finalization failed' }

$DeliveryName = -join ([char[]]@(0x6700,0x65b0,0x7248,0x6784,0x5efa))
$DefaultDelivery = Join-Path (Split-Path $Root -Parent) $DeliveryName
$Delivery = if ($env:VIBE_RELEASE_DELIVERY) { [IO.Path]::GetFullPath($env:VIBE_RELEASE_DELIVERY) } else { $DefaultDelivery }
$resolvedParent = (Resolve-Path -LiteralPath (Split-Path $Root -Parent)).Path
if (!$Delivery.StartsWith($resolvedParent + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
  throw "Refusing delivery path outside workspace parent: $Delivery"
}
if (Test-Path -LiteralPath $Delivery) {
  throw "Refusing to delete existing delivery path; choose a new isolated VIBE_RELEASE_DELIVERY: $Delivery"
}
New-Item -ItemType Directory -Path $Delivery -Force | Out-Null
Copy-Item -Path (Join-Path $Unpacked '*') -Destination $Delivery -Recurse -Force
Copy-Item -LiteralPath $Installer -Destination (Join-Path $Delivery (Split-Path -Leaf $Installer)) -Force
foreach ($name in @('runtime-manifest.json','SBOM.cdx.json','SBOM.spdx.json','LICENSE','THIRD_PARTY_NOTICES.md','README.md')) {
  Copy-Item -LiteralPath (Join-Path $Root $name) -Destination (Join-Path $Delivery $name) -Force
}
Copy-Item -LiteralPath (Join-Path $Root 'release\SHA256SUMS.txt') -Destination (Join-Path $Delivery 'SHA256SUMS.txt') -Force

& (Join-Path $PSScriptRoot 'Test-ProductIdentity.ps1') | Write-Host
if ($LASTEXITCODE -ne 0) { throw 'Product identity gate failed after release finalization' }
& (Join-Path $PSScriptRoot 'Test-License.ps1') | Write-Host
if ($LASTEXITCODE -ne 0) { throw 'License gate failed after release finalization' }

[ordered]@{
  ok = $true
  release_eligible = $true
  recovery = 'existing_packaged_artifacts_revalidated'
  installer = Split-Path -Leaf $Installer
  installer_sha256 = (Get-FileHash -LiteralPath $Installer -Algorithm SHA256).Hash.ToLowerInvariant()
  executable_sha256 = (Get-FileHash -LiteralPath $Executable -Algorithm SHA256).Hash.ToLowerInvariant()
  codex_sha256 = ([string]$Codex.sha256).ToLowerInvariant()
  claude_distribution = 'external_optional_not_bundled'
  delivery = $Delivery
} | ConvertTo-Json -Depth 4
