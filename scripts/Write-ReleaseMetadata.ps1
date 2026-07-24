[CmdletBinding()]
param(
  [switch]$MetadataOnly,
  [string]$RuntimeRoot = 'runtime-release'
)

$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot
$Package = Get-Content (Join-Path $Root 'package.json') -Raw -Encoding UTF8 | ConvertFrom-Json
$ResolvedRuntimeRoot = if ([IO.Path]::IsPathRooted($RuntimeRoot)) {
  [IO.Path]::GetFullPath($RuntimeRoot)
} else {
  [IO.Path]::GetFullPath((Join-Path $Root $RuntimeRoot))
}
$RuntimeManifestPath = Join-Path $ResolvedRuntimeRoot 'manifest.json'
$RuntimeSummaryPath = Join-Path $ResolvedRuntimeRoot 'manifest.summary.json'
$MetadataPython = Join-Path $ResolvedRuntimeRoot 'python\python.exe'
$Generator = Join-Path $PSScriptRoot 'write_release_sbom.py'
foreach ($required in @($RuntimeManifestPath, $RuntimeSummaryPath, $MetadataPython, $Generator)) {
  if (!(Test-Path -LiteralPath $required -PathType Leaf)) {
    throw "Release metadata input is missing: $required"
  }
}

& $MetadataPython -X utf8 $Generator $ResolvedRuntimeRoot
if ($LASTEXITCODE -ne 0) {
  throw "Release SBOM generation failed with exit code $LASTEXITCODE"
}

if (!$MetadataOnly) {
  $installer = Get-Item -LiteralPath (Join-Path $Root "release\Vibe-Research-$($Package.version)-Setup.exe")
  $exe = Get-Item -LiteralPath (Join-Path $Root 'release\win-unpacked\Vibe Research.exe')
  @(
    "$((Get-FileHash -LiteralPath $exe.FullName -Algorithm SHA256).Hash)  Vibe Research.exe",
    "$((Get-FileHash -LiteralPath $installer.FullName -Algorithm SHA256).Hash)  $($installer.Name)"
  ) | Set-Content (Join-Path $Root 'release\SHA256SUMS.txt') -Encoding ASCII
}
