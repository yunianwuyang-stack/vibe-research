[CmdletBinding()]
param([switch]$AllowLocalValidation)
$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot
if (Test-Path (Join-Path $Root 'backend\license.json')) { throw 'Bundled product license state must not ship in source or release payloads' }
foreach ($required in 'LICENSE','THIRD_PARTY_NOTICES.md','SBOM.spdx.json','SBOM.cdx.json') { if (!(Test-Path (Join-Path $Root $required))) { throw "Missing $required" } }
$sbom = Get-Content -Raw (Join-Path $Root 'SBOM.spdx.json') | ConvertFrom-Json
if ($sbom.spdxVersion -notlike 'SPDX-2.3*' -or !$sbom.packages) { throw 'Invalid SPDX SBOM' }
foreach ($componentName in @('OpenAI Codex CLI')) {
  if ($componentName -notin @($sbom.packages | ForEach-Object { $_.name })) { throw "Bundled CLI missing from SPDX SBOM: $componentName" }
}
if (!@($sbom.relationships | Where-Object { $_.relationshipType -eq 'CONTAINS' })) { throw 'SPDX dependency relationships are missing' }
if ('Claude Code' -in @($sbom.packages | ForEach-Object { $_.name })) {
  throw 'External Claude adapter must not be represented as a shipped SPDX package'
}
if (@($sbom.hasExtractedLicensingInfos | Where-Object { $_.licenseId -match 'Claude' -or $_.name -match 'Claude' })) {
  throw 'External Claude adapter must not add bundled licensing text to the SPDX SBOM'
}
$cyclone = Get-Content -Raw (Join-Path $Root 'SBOM.cdx.json') | ConvertFrom-Json
if ($cyclone.bomFormat -ne 'CycloneDX' -or !$cyclone.components) { throw 'Invalid CycloneDX SBOM' }
if (!$cyclone.dependencies -or !$cyclone.dependencies[0].dependsOn) { throw 'CycloneDX dependency graph is missing' }
$claudeComponent = @($cyclone.components | Where-Object { $_.name -eq 'Claude Code' }) | Select-Object -First 1
if ($claudeComponent) { throw 'External Claude adapter must not be represented as a shipped CycloneDX component' }
$externalClaudeProperty = @($cyclone.metadata.properties | Where-Object { $_.name -eq 'vibe:external-adapter:claude' }) | Select-Object -First 1
if (!$externalClaudeProperty) { throw 'CycloneDX external Claude adapter metadata is missing' }
$externalClaudeMetadata = $externalClaudeProperty.value | ConvertFrom-Json
if ($externalClaudeMetadata.bundled -ne $false -or $externalClaudeMetadata.required -ne $false) {
  throw 'CycloneDX external Claude adapter metadata is invalid'
}
$notices = Get-Content -Raw (Join-Path $Root 'THIRD_PARTY_NOTICES.md') -Encoding UTF8
if ($notices -notmatch 'Claude Code \(optional external adapter\)' -or $notices -notmatch 'not bundled' -or $notices -notmatch 'OpenAI Codex CLI') {
  throw 'CLI license status is missing from third-party notices'
}

function Test-RuntimeNotices([string]$RuntimeRoot) {
  if (!(Test-Path -LiteralPath $RuntimeRoot -PathType Container)) { return }
  foreach ($relative in @(
    'manifest.json','manifest.summary.json','node\LICENSE','python\LICENSE.txt',
    'agents\codex\LICENSE','agents\codex\NOTICE',
    'agents\codex\ripgrep\COPYING','agents\codex\ripgrep\LICENSE-MIT','agents\codex\ripgrep\UNLICENSE'
  )) {
    if (!(Test-Path -LiteralPath (Join-Path $RuntimeRoot $relative) -PathType Leaf)) {
      throw "Missing bundled runtime notice or manifest: $RuntimeRoot\$relative"
    }
  }
  $runtimeManifest = Get-Content -Raw -LiteralPath (Join-Path $RuntimeRoot 'manifest.summary.json') -Encoding UTF8 | ConvertFrom-Json
  $externalClaude = $runtimeManifest.external_adapters.claude
  if (!$externalClaude -or $externalClaude.bundled -ne $false -or $externalClaude.required -ne $false) {
    throw 'Runtime manifest does not declare Claude as an external optional adapter'
  }
  foreach ($forbidden in @(
    'agents\claude',
    'node\node_modules\@anthropic-ai\claude-code',
    'node\node_modules\.bin\claude',
    'node\node_modules\.bin\claude.cmd',
    'node\node_modules\.bin\claude.ps1',
    'node\claude','node\claude.cmd','node\claude.ps1','node\claude.exe'
  )) {
    if (Test-Path -LiteralPath (Join-Path $RuntimeRoot $forbidden)) {
      throw "Claude payload must not be bundled: $RuntimeRoot\$forbidden"
    }
  }
  if (!$runtimeManifest.release_eligible) {
    if (!$AllowLocalValidation) {
      throw "Runtime is not eligible for redistribution: $($runtimeManifest.release_blockers -join ', ')"
    }
    if ($runtimeManifest.build_purpose -ne 'local_validation_only' -or !$runtimeManifest.release_blockers) {
      throw 'Non-distributable runtime is not explicitly and completely marked as local validation only'
    }
  }
}

Test-RuntimeNotices (Join-Path $Root 'runtime-release')
$packagedResources = Join-Path $Root 'release\win-unpacked\resources'
$packagedApp = if (Test-Path -LiteralPath (Join-Path $packagedResources 'app.asar.unpacked') -PathType Container) {
  Join-Path $packagedResources 'app.asar.unpacked'
} else {
  Join-Path $packagedResources 'app'
}
$packagedRuntime = Join-Path $packagedResources 'runtime'
if (Test-Path -LiteralPath $packagedApp -PathType Container) {
  if (Test-Path -LiteralPath (Join-Path $packagedApp 'backend\license.json')) {
    throw 'Bundled product license state is present in the unpacked application'
  }
  Test-RuntimeNotices $packagedRuntime
}
$patterns = 'api[_-]?key\s*[:=]','access[_-]?token\s*[:=]','client[_-]?secret\s*[:=]','password\s*[:=]'
$files = @(
  Get-ChildItem (Join-Path $Root 'backend') -Recurse -File -Include *.py,*.js,*.ts,*.tsx,*.json,*.ps1
  Get-Item (Join-Path $Root 'main.js'),(Join-Path $Root 'preload.js')
) | Where-Object { $_.FullName -notmatch '\\(node_modules|runtime|\.git)\\' }
foreach ($pattern in $patterns) {
 $hits = Select-String -Path $files.FullName -Pattern $pattern -CaseSensitive:$false
 foreach ($hit in $hits) {
   if ($hit.Line -notmatch 'os\.environ|settings\.get|def |_request_json|if (?:not )?(?:self\._)?api_key\s*:|(?:clear_)?api_key:\s*(?:str|bool)|api_key\s*=\s*(?:str\(|api_key\b|["'']{2}|None\b)|password\s*:\s*(?:str|bytes)|password\s*:\s*[A-Za-z_$]|password = _SALT_PREFIX|password = b"transport:"') {
     throw "Potential embedded credential literal: $($hit.Path):$($hit.LineNumber)"
   }
 }
}
Push-Location $Root
git diff --check
Pop-Location
Write-Output 'LICENSE_AUDIT_PASS'
