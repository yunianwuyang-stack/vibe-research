[CmdletBinding()]
param([string]$Unpacked = "release\win-unpacked")
$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot

# Identity is enforced from the product's canonical declarations instead of
# retaining obsolete vendor strings in the repository as a deny-list.
$package = Get-Content -Raw -LiteralPath (Join-Path $Root 'package.json') -Encoding UTF8 | ConvertFrom-Json
if ($package.name -ne 'vibe-research') { throw 'package.name is not vibe-research' }
if ($package.author -ne 'Vibe Research Project') { throw 'package.author is not Vibe Research Project' }
if ($package.build.appId -ne 'com.viberesearch.workbench') { throw 'build.appId is not canonical' }
if ($package.build.productName -ne 'Vibe Research') { throw 'build.productName is not Vibe Research' }
if ($package.build.executableName -ne 'Vibe Research') { throw 'build.executableName is not Vibe Research' }
if ($package.build.artifactName -ne 'Vibe-Research-${version}-Setup.${ext}') { throw 'build.artifactName is not canonical' }

$requiredFiles = @(
  'main.js','preload.js','updater.js','updater-config.json','package.json',
  'backend\main.py','backend\config.py','frontend\src\api.ts','dist\index.html'
) | ForEach-Object { Join-Path $Root $_ }
foreach ($file in $requiredFiles) {
  if (!(Test-Path -LiteralPath $file)) { throw "Required identity surface is missing: $file" }
}

$declaredText = $requiredFiles | ForEach-Object {
  Get-Content -Raw -LiteralPath $_ -Encoding UTF8
}
if (($declaredText -join "`n") -notmatch 'Vibe Research') {
  throw 'Canonical Vibe Research identity is absent from production surfaces'
}

# Product-owned runtime variables use one namespace. This catches stale
# migration prefixes without embedding any previous product identity.
$firstPartyRoots = @('backend','frontend\src','skills','tools') | ForEach-Object { Join-Path $Root $_ }
$firstPartyFiles = @($firstPartyRoots | ForEach-Object {
  Get-ChildItem -LiteralPath $_ -Recurse -File -ErrorAction SilentlyContinue |
    Where-Object { $_.Extension -in '.py','.js','.jsx','.ts','.tsx','.json','.md','.yaml','.yml','.toml','.ps1','.sh' }
}) + @((Join-Path $Root 'main.js'), (Join-Path $Root 'preload.js'), (Join-Path $Root 'updater.js'))
$firstPartyPaths = $firstPartyFiles | ForEach-Object { if ($_ -is [IO.FileInfo]) { $_.FullName } else { [string]$_ } }
$namespacePattern = '["''](?!VIBE_)[A-Z]{2,16}_(FAST_MODE|PYTHON|SCREENSHOT_TOOL|RUNTIME_ROOT|DESKTOP|LOCAL_SESSION_TOKEN)["'']'
$namespaceHits = Select-String -LiteralPath $firstPartyPaths -Pattern $namespacePattern -CaseSensitive -Encoding UTF8 -ErrorAction SilentlyContinue
if ($namespaceHits) { throw "Non-canonical product runtime namespace found: $($namespaceHits.Path -join ', ')" }

$unpackedRoot = Join-Path $Root $Unpacked
$resourcesRoot = Join-Path $unpackedRoot 'resources'
$appRoot = Join-Path $resourcesRoot 'app'
$asarPath = Join-Path $resourcesRoot 'app.asar'
$unpackedAppRoot = Join-Path $resourcesRoot 'app.asar.unpacked'
if (Test-Path -LiteralPath $asarPath -PathType Leaf) {
  foreach ($relative in @('backend\main.py','backend\config.py')) {
    $source = Join-Path $Root $relative
    $built = Join-Path $unpackedAppRoot $relative
    if (!(Test-Path -LiteralPath $built) -or (Get-FileHash -LiteralPath $source).Hash -ne (Get-FileHash -LiteralPath $built).Hash) {
      throw "Packaged/source mismatch: $relative"
    }
  }
  $exe = Join-Path $unpackedRoot 'Vibe Research.exe'
  if (!(Test-Path -LiteralPath $exe)) { throw 'Packaged Vibe Research executable is missing' }
  $info = (Get-Item -LiteralPath $exe).VersionInfo
  if ($info.ProductName -ne 'Vibe Research' -or $info.FileDescription -ne 'Vibe Research' -or
      ($info.OriginalFilename -ne '' -and $info.OriginalFilename -ne 'Vibe Research.exe')) {
    throw 'Windows version resource is not Vibe Research'
  }
} elseif (Test-Path -LiteralPath $appRoot) {
  foreach ($relative in @('main.js','preload.js','backend\main.py','dist\index.html')) {
    $source = Join-Path $Root $relative
    $built = Join-Path $appRoot $relative
    if (!(Test-Path -LiteralPath $built) -or (Get-FileHash -LiteralPath $source).Hash -ne (Get-FileHash -LiteralPath $built).Hash) {
      throw "Packaged/source mismatch: $relative"
    }
  }
  $exe = Join-Path $unpackedRoot 'Vibe Research.exe'
  if (!(Test-Path -LiteralPath $exe)) { throw 'Packaged Vibe Research executable is missing' }
  $info = (Get-Item -LiteralPath $exe).VersionInfo
  if ($info.ProductName -ne 'Vibe Research' -or $info.FileDescription -ne 'Vibe Research' -or
      ($info.OriginalFilename -ne '' -and $info.OriginalFilename -ne 'Vibe Research.exe')) {
    throw 'Windows version resource is not Vibe Research'
  }
}

[ordered]@{
  ok = $true
  product = 'Vibe Research'
  package_name = $package.name
  unpacked_present = ((Test-Path -LiteralPath $asarPath -PathType Leaf) -or (Test-Path -LiteralPath $appRoot))
  checked_at_utc = [DateTime]::UtcNow.ToString('o')
} | ConvertTo-Json
