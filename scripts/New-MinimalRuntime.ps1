[CmdletBinding()]
param(
  [string]$Destination = "runtime-release",
  [switch]$LocalValidationOnly
)

$ErrorActionPreference = 'Stop'
$script:stageMutex = $null
$script:stageMutexHeld = $false
function Exit-StageMutex {
  if ($script:stageMutexHeld -and $script:stageMutex) {
    try { $script:stageMutex.ReleaseMutex() } catch {}
    $script:stageMutexHeld = $false
  }
  if ($script:stageMutex) {
    $script:stageMutex.Dispose()
    $script:stageMutex = $null
  }
}
trap {
  $failure = $_
  Exit-StageMutex
  throw $failure
}
$Root = (Resolve-Path (Split-Path -Parent $PSScriptRoot)).Path
$Source = Join-Path $Root 'runtime'
$CliLockPath = Join-Path $Root 'build\agent-cli-lock.json'
$TrackedLicenses = Join-Path $Root 'licenses'
$Dest = if ([IO.Path]::IsPathRooted($Destination)) {
  [IO.Path]::GetFullPath($Destination)
} else {
  [IO.Path]::GetFullPath((Join-Path $Root $Destination))
}

# The staging directory is disposable, but an accidental absolute Destination
# must never turn the cleanup below into an arbitrary recursive delete.
$rootPrefix = $Root.TrimEnd([IO.Path]::DirectorySeparatorChar) + [IO.Path]::DirectorySeparatorChar
if (!$Dest.StartsWith($rootPrefix, [StringComparison]::OrdinalIgnoreCase)) {
  throw "Runtime staging destination must stay inside the repository: $Dest"
}
if (!(Test-Path -LiteralPath $Source -PathType Container)) {
  throw "Source runtime is missing: $Source"
}
if (!(Test-Path -LiteralPath $CliLockPath -PathType Leaf)) {
  throw "Pinned Agent CLI lock is missing: $CliLockPath"
}
$CliLock = Get-Content -LiteralPath $CliLockPath -Raw -Encoding UTF8 | ConvertFrom-Json
if ($CliLock.schema_version -ne '1.0' -or $CliLock.target -ne 'win32-x64') {
  throw 'Pinned Agent CLI lock has an unsupported schema or target'
}
if (!$CliLock.registry.StartsWith('https://', [StringComparison]::OrdinalIgnoreCase)) {
  throw 'Pinned Agent CLI registry must use HTTPS'
}
foreach ($adapterName in @('codex')) {
  $locked = $CliLock.adapters.$adapterName
  if (!$locked -or !$locked.npm_package -or !$locked.version -or !$locked.integrity -or !$locked.license) {
    throw "Pinned Agent CLI lock is incomplete for $adapterName"
  }
}
$externalClaudeLock = $CliLock.adapters.claude
$externalClaudeProperties = @($externalClaudeLock.PSObject.Properties.Name)
if (
  !$externalClaudeLock -or
  !($externalClaudeProperties -contains 'bundled') -or
  [bool]$externalClaudeLock.bundled -or
  !($externalClaudeProperties -contains 'required') -or
  [bool]$externalClaudeLock.required -or
  $externalClaudeLock.install_mode -ne 'external_user_managed' -or
  $externalClaudeLock.redistribution_status -ne 'not_bundled_external_optional'
) {
  throw 'Claude must be declared as an optional, user-managed external adapter'
}
$requiredClaudeDiscovery = @('CLAUDE_BIN', 'PATH', 'saved_setting')
foreach ($discoveryMethod in $requiredClaudeDiscovery) {
  if (@($externalClaudeLock.discovery) -notcontains $discoveryMethod) {
    throw "External Claude discovery is missing: $discoveryMethod"
  }
}
$externalAdapters = [ordered]@{
  claude = [ordered]@{
    bundled = $false
    required = $false
    install_mode = [string]$externalClaudeLock.install_mode
    redistribution_status = [string]$externalClaudeLock.redistribution_status
    discovery = @($externalClaudeLock.discovery)
  }
}
$releaseBlockers = New-Object System.Collections.ArrayList
if ($CliLock.adapters.codex.redistribution_status -ne 'permitted_by_apache_2_0') {
  [void]$releaseBlockers.Add('codex_redistribution_not_permitted_by_lock')
}
$releaseEligible = $releaseBlockers.Count -eq 0
if (!$releaseEligible -and !$LocalValidationOnly) {
  throw "Runtime is not release eligible: $($releaseBlockers -join ', '). Use -LocalValidationOnly only for non-distributable local E2E staging."
}
$mutexHasher = [Security.Cryptography.SHA256]::Create()
try {
  $mutexDigest = $mutexHasher.ComputeHash([Text.Encoding]::UTF8.GetBytes($Dest))
} finally {
  $mutexHasher.Dispose()
}
$mutexSuffix = ([BitConverter]::ToString($mutexDigest, 0, 12)).Replace('-', '')
$stageMutex = New-Object Threading.Mutex($false, "Local\VibeResearchRuntimeStage-$mutexSuffix")
$stageMutexHeld = $stageMutex.WaitOne(0)
if (!$stageMutexHeld) {
  $stageMutex.Dispose()
  throw "Another runtime staging process already owns this destination: $Dest"
}
if (Test-Path -LiteralPath $Dest) {
  $removed = $false
  for ($attempt = 1; $attempt -le 8; $attempt++) {
    try {
      Remove-Item -LiteralPath $Dest -Recurse -Force -ErrorAction Stop
      $removed = !(Test-Path -LiteralPath $Dest)
      if ($removed) { break }
    } catch {
      if ($attempt -eq 8) { throw }
    }
    Start-Sleep -Milliseconds (250 * $attempt)
  }
  if (!$removed) { throw "Unable to clean runtime staging directory: $Dest" }
}
New-Item -ItemType Directory -Path $Dest -Force | Out-Null

function Copy-RequiredTree([string]$Name) {
  $from = Join-Path $Source $Name
  if (!(Test-Path -LiteralPath $from -PathType Container)) {
    throw "Required runtime directory is missing: runtime/$Name"
  }
  Copy-Item -LiteralPath $from -Destination (Join-Path $Dest $Name) -Recurse
}

# These are production capabilities, not optional developer conveniences.
# Git Bash supports command-oriented workflows, while the paper workflows
# require an offline XeLaTeX/MiKTeX tree.
foreach ($name in @('node', 'pandoc', 'draw.io', 'git', 'texlive')) {
  Copy-RequiredTree $name
}

# Preserve the upstream runtime licenses at the same level as the executable
# they govern.  The source Node distribution was previously minimized without
# its LICENSE, so use the version-matched tracked copy obtained from upstream.
$nodeLicenseSource = Join-Path $TrackedLicenses 'Node.js-LICENSE.txt'
$pythonLicenseSource = Join-Path $Source 'python\LICENSE.txt'
foreach ($requiredLicense in @($nodeLicenseSource, $pythonLicenseSource)) {
  if (!(Test-Path -LiteralPath $requiredLicense -PathType Leaf)) {
    throw "Required runtime license is missing: $requiredLicense"
  }
}
Copy-Item -LiteralPath $nodeLicenseSource -Destination (Join-Path $Dest 'node\LICENSE')

$nodeRoot = Join-Path $Dest 'node'
$bundledClaudePayloads = @(
  'node_modules\@anthropic-ai\claude-code',
  'node_modules\.bin\claude',
  'node_modules\.bin\claude.cmd',
  'node_modules\.bin\claude.ps1',
  'node_modules\.bin\claude.exe',
  'claude',
  'claude.cmd',
  'claude.ps1',
  'claude.exe'
)
function Remove-BundledClaudePayload([string]$RuntimeNodeRoot) {
  foreach ($relativePath in $bundledClaudePayloads) {
    $candidate = Join-Path $RuntimeNodeRoot $relativePath
    if (Test-Path -LiteralPath $candidate) {
      Remove-Item -LiteralPath $candidate -Recurse -Force
    }
  }
}

# The source Node tree may have been provisioned for local development. Claude
# remains discoverable from the user's environment, but its package, native
# executable, and npm shims must never cross into a redistributable runtime.
Remove-BundledClaudePayload $nodeRoot

$npmCommand = Join-Path $nodeRoot 'npm.cmd'
if (!(Test-Path -LiteralPath $npmCommand -PathType Leaf)) {
  throw 'Bundled npm is required to install the pinned Codex CLI'
}

function Assert-RegistryIntegrity([object]$PackageLock) {
  $packageSpec = "$($PackageLock.npm_package)@$($PackageLock.version)"
  $observedJson = & $npmCommand view $packageSpec 'dist.integrity' --json "--registry=$($CliLock.registry)"
  if ($LASTEXITCODE -ne 0) {
    throw "Unable to resolve pinned npm provenance for $packageSpec"
  }
  $observed = [string]($observedJson | ConvertFrom-Json)
  if ($observed -ne [string]$PackageLock.integrity) {
    throw "Registry integrity differs from the lock for $packageSpec"
  }

  # npm optional-dependency aliases (for example
  # @openai/codex-win32-x64 -> npm:@openai/codex@...-win32-x64) are install
  # paths, not independently published registry package names.
  $platformRegistryPackage = if ($PackageLock.platform_registry_package) {
    [string]$PackageLock.platform_registry_package
  } else {
    [string]$PackageLock.platform_package
  }
  $platformSpec = "$platformRegistryPackage@$($PackageLock.platform_version)"
  $platformJson = & $npmCommand view $platformSpec 'dist.integrity' --json "--registry=$($CliLock.registry)"
  if ($LASTEXITCODE -ne 0) {
    throw "Unable to resolve pinned npm provenance for $platformSpec"
  }
  $platformObserved = [string]($platformJson | ConvertFrom-Json)
  if ($platformObserved -ne [string]$PackageLock.platform_integrity) {
    throw "Registry integrity differs from the lock for $platformSpec"
  }
}

$codexLock = $CliLock.adapters.codex
Assert-RegistryIntegrity $codexLock

# Install the exact CLI packages into a fresh ASCII-safe prefix, then copy the
# verified trees into the portable runtime. npm has known extraction failures
# when deeply nested optional packages are installed directly below a Unicode
# release path; staging first makes Unicode installation directories a tested
# copy/runtime concern rather than a package-manager limitation. Lifecycle
# scripts remain disabled.
$cliInstallPrefix = Join-Path $env:TEMP ("vibe-agent-cli-stage-{0}" -f ([guid]::NewGuid().ToString('N')))
try {
  New-Item -ItemType Directory -Path $cliInstallPrefix -Force | Out-Null
  & $npmCommand install --global --ignore-scripts --omit=dev --no-audit --no-fund --no-update-notifier `
    "--prefix=$cliInstallPrefix" "--registry=$($CliLock.registry)" `
    "$($codexLock.npm_package)@$($codexLock.version)"
  if ($LASTEXITCODE -ne 0) {
    throw "Pinned Agent CLI installation failed with exit code $LASTEXITCODE"
  }

  foreach ($package in @(
    [ordered]@{ source = 'node_modules\@openai\codex'; destination = 'node_modules\@openai\codex' }
  )) {
    $packageSource = Join-Path $cliInstallPrefix $package.source
    $packageDestination = Join-Path $nodeRoot $package.destination
    if (!(Test-Path -LiteralPath $packageSource -PathType Container)) {
      throw "Pinned Agent CLI package was not extracted: $($package.source)"
    }
    if (Test-Path -LiteralPath $packageDestination) {
      Remove-Item -LiteralPath $packageDestination -Recurse -Force
    }
    New-Item -ItemType Directory -Path (Split-Path -Parent $packageDestination) -Force | Out-Null
    Copy-Item -LiteralPath $packageSource -Destination $packageDestination -Recurse
  }
  foreach ($shim in @('codex', 'codex.cmd', 'codex.ps1')) {
    $shimSource = Join-Path $cliInstallPrefix $shim
    if (Test-Path -LiteralPath $shimSource -PathType Leaf) {
      Copy-Item -LiteralPath $shimSource -Destination (Join-Path $nodeRoot $shim) -Force
    }
  }
} finally {
  if (Test-Path -LiteralPath $cliInstallPrefix) {
    Remove-Item -LiteralPath $cliInstallPrefix -Recurse -Force -ErrorAction SilentlyContinue
  }
}

# Re-apply the exclusion after npm staging and fail closed if a future source
# or installer layout reintroduces any known bundled Claude payload.
Remove-BundledClaudePayload $nodeRoot
foreach ($relativePath in $bundledClaudePayloads) {
  $candidate = Join-Path $nodeRoot $relativePath
  if (Test-Path -LiteralPath $candidate) {
    throw "External-only Claude payload leaked into runtime staging: $relativePath"
  }
}

$codexPackagePath = Join-Path $nodeRoot 'node_modules\@openai\codex\package.json'
$codexPlatformPath = Join-Path $nodeRoot 'node_modules\@openai\codex\node_modules\@openai\codex-win32-x64\package.json'
foreach ($packagePath in @($codexPackagePath, $codexPlatformPath)) {
  if (!(Test-Path -LiteralPath $packagePath -PathType Leaf)) {
    throw "Bundled Agent CLI package metadata is missing: $packagePath"
  }
}
$codexPackage = Get-Content -LiteralPath $codexPackagePath -Raw -Encoding UTF8 | ConvertFrom-Json
$codexPlatform = Get-Content -LiteralPath $codexPlatformPath -Raw -Encoding UTF8 | ConvertFrom-Json
if ($codexPackage.name -ne $codexLock.npm_package -or $codexPackage.version -ne $codexLock.version -or $codexPackage.license -ne 'Apache-2.0') {
  throw 'Installed Codex package does not match the pinned package, version, or license'
}
$codexPlatformPublishedName = if ($codexLock.platform_registry_package) {
  [string]$codexLock.platform_registry_package
} else {
  [string]$codexLock.platform_package
}
if ($codexPlatform.name -ne $codexPlatformPublishedName -or $codexPlatform.version -ne $codexLock.platform_version -or $codexPlatform.license -ne 'Apache-2.0') {
  throw 'Installed native Codex package does not match the pinned package, version, or license'
}
$codexVendor = Join-Path $nodeRoot 'node_modules\@openai\codex\node_modules\@openai\codex-win32-x64\vendor'
$codexExecutables = @(Get-ChildItem -LiteralPath $codexVendor -Recurse -File -Filter 'codex.exe' -ErrorAction SilentlyContinue |
  Where-Object { $_.FullName -match '[\\/]bin[\\/]codex\.exe$' })
if ($codexExecutables.Count -ne 1) {
  throw "Expected one pinned native Codex executable, found $($codexExecutables.Count)"
}
$codexExecutable = $codexExecutables[0].FullName
$ripgrepExecutables = @(Get-ChildItem -LiteralPath $codexVendor -Recurse -File -Filter 'rg.exe' -ErrorAction SilentlyContinue |
  Where-Object { $_.FullName -match '[\\/]codex-path[\\/]rg\.exe$' })
if ($ripgrepExecutables.Count -ne 1) {
  throw "Expected one Codex-bundled ripgrep executable, found $($ripgrepExecutables.Count)"
}
$ripgrepExecutable = $ripgrepExecutables[0].FullName

$agentLicenseRoot = Join-Path $Dest 'agents'
$codexLicenseRoot = Join-Path $agentLicenseRoot 'codex'
New-Item -ItemType Directory -Path $codexLicenseRoot -Force | Out-Null
Copy-Item -LiteralPath (Join-Path $TrackedLicenses 'OpenAI-Codex-LICENSE.txt') -Destination (Join-Path $codexLicenseRoot 'LICENSE')
Copy-Item -LiteralPath (Join-Path $TrackedLicenses 'OpenAI-Codex-NOTICE.txt') -Destination (Join-Path $codexLicenseRoot 'NOTICE')
$ripgrepLicenseRoot = Join-Path $codexLicenseRoot 'ripgrep'
New-Item -ItemType Directory -Path $ripgrepLicenseRoot -Force | Out-Null
Copy-Item -LiteralPath (Join-Path $TrackedLicenses 'ripgrep-COPYING') -Destination (Join-Path $ripgrepLicenseRoot 'COPYING')
Copy-Item -LiteralPath (Join-Path $TrackedLicenses 'ripgrep-LICENSE-MIT') -Destination (Join-Path $ripgrepLicenseRoot 'LICENSE-MIT')
Copy-Item -LiteralPath (Join-Path $TrackedLicenses 'ripgrep-UNLICENSE') -Destination (Join-Path $ripgrepLicenseRoot 'UNLICENSE')

# Keep the signed upstream bootstrapper as a repair path. Normal operation uses
# the already bundled portable MiKTeX tree and therefore remains offline.
$miktexSetup = Join-Path $Source 'miktex-setup.exe'
if (!(Test-Path -LiteralPath $miktexSetup -PathType Leaf)) {
  throw 'Required runtime repair asset is missing: runtime/miktex-setup.exe'
}
Copy-Item -LiteralPath $miktexSetup -Destination (Join-Path $Dest 'miktex-setup.exe')

$pythonSource = Join-Path $Source 'python'
if (!(Test-Path -LiteralPath (Join-Path $pythonSource 'python.exe') -PathType Leaf)) {
  throw 'Required runtime interpreter is missing: runtime/python/python.exe'
}
$pythonDest = Join-Path $Dest 'python'
New-Item -ItemType Directory -Path $pythonDest -Force | Out-Null
Copy-Item -LiteralPath $pythonLicenseSource -Destination (Join-Path $pythonDest 'LICENSE.txt')

# The embedded interpreter imports its stdlib from python311.zip. Copy the
# native extension DLLs and interpreter metadata, but never stale Scripts/*.exe
# launchers whose shebangs can contain an absolute build-machine path.
Get-ChildItem -LiteralPath $pythonSource -File |
  Where-Object { $_.Name -match '^python|^vcruntime|^libcrypto|^libssl|^libffi|^sqlite3|^select|^unicodedata|^pyexpat|^_' } |
  Copy-Item -Destination $pythonDest
if (Test-Path -LiteralPath (Join-Path $pythonSource 'DLLs')) {
  Copy-Item -LiteralPath (Join-Path $pythonSource 'DLLs') -Destination (Join-Path $pythonDest 'DLLs') -Recurse
}

$site = Join-Path $pythonSource 'Lib\site-packages'
$targetSite = Join-Path $pythonDest 'Lib\site-packages'
if (!(Test-Path -LiteralPath $site -PathType Container)) {
  throw "Python site-packages is missing: $site"
}
New-Item -ItemType Directory -Path $targetSite -Force | Out-Null

# Explicit allow-list for the API, document ingestion/export and shipped
# scientific/figure skills. A requirement is useful only if its package is
# actually copied into the portable interpreter.
$packagePatterns = @(
  'fastapi*', 'starlette*', 'pydantic*', 'aiosqlite*', 'uvicorn*',
  'click*', 'colorama*', 'dotenv', 'python_dotenv*',
  'h11*', 'httptools*', 'anyio*', 'sniffio*', 'idna*',
  'typing_extensions*', 'typing_inspection*', 'annotated_types*', 'annotated_doc*',
  'multipart*', 'python_multipart*',
  'cryptography*', 'cffi*', '_cffi_backend*', 'pycparser*',
  'websockets*', 'watchfiles*', 'watchdog*',
  'certifi*', 'charset_normalizer*', '*__mypyc*', 'requests*', 'urllib3*', 'yaml*', 'PyYAML*',
  'PIL', 'Pillow*',
  'pymupdf*', 'fitz', 'PyPDF2', 'pypdf2-*.dist-info', 'pypdf', 'pypdf-*.dist-info',
  'docx', 'python_docx*', 'lxml*',
  'numpy*', 'scipy*', 'pandas*', 'matplotlib*', 'mpl_toolkits', 'seaborn*',
  'contourpy*', 'cycler*', 'fontTools*', 'kiwisolver*', 'packaging*', 'pyparsing*',
  'dateutil', 'python_dateutil*', 'pytz*', 'tzdata*', 'six*',
  'openpyxl*', 'et_xmlfile*'
)

$copied = New-Object 'System.Collections.Generic.HashSet[string]' ([StringComparer]::OrdinalIgnoreCase)
foreach ($pattern in $packagePatterns) {
  foreach ($item in Get-ChildItem -LiteralPath $site -Force -Filter $pattern -ErrorAction SilentlyContinue) {
    if ($item.Extension -eq '.whl') { continue }
    if ($copied.Add($item.FullName)) {
      Copy-Item -LiteralPath $item.FullName -Destination $targetSite -Recurse
    }
  }
}

# Runtime packages are copied from wheels that may contain upstream tests,
# caches, bytecode and source maps. They are not required at runtime and must
# not enter the redistributable payload.
Get-ChildItem -LiteralPath $targetSite -Directory -Recurse -Force -ErrorAction SilentlyContinue |
  Where-Object { $_.Name -in @('test', 'tests', 'testing', '__tests__', '__pycache__', '.pytest_cache') } |
  Sort-Object { $_.FullName.Length } -Descending |
  Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
Get-ChildItem -LiteralPath $targetSite -File -Recurse -Force -ErrorAction SilentlyContinue |
  Where-Object { $_.Extension -in @('.pyc', '.pyo', '.map') } |
  Remove-Item -Force -ErrorAction SilentlyContinue

$requiredFiles = [ordered]@{
  python = 'python\python.exe'
  node = 'node\node.exe'
  codex = $codexExecutable.Substring($Dest.Length + 1)
  ripgrep = $ripgrepExecutable.Substring($Dest.Length + 1)
  git = 'git\cmd\git.exe'
  bash = 'git\bin\bash.exe'
  pandoc = 'pandoc\pandoc.exe'
  drawio = 'draw.io\draw.io.exe'
  xelatex = 'texlive\texmfs\install\miktex\bin\x64\xelatex.exe'
  pdflatex = 'texlive\texmfs\install\miktex\bin\x64\pdflatex.exe'
  latexmk = 'texlive\texmfs\install\miktex\bin\x64\latexmk.exe'
  biber = 'texlive\texmfs\install\miktex\bin\x64\biber.exe'
}
foreach ($entry in $requiredFiles.GetEnumerator()) {
  $candidate = Join-Path $Dest $entry.Value
  if (!(Test-Path -LiteralPath $candidate -PathType Leaf)) {
    throw "Runtime staging is incomplete: $($entry.Key) is missing at $($entry.Value)"
  }
}

$portableTeXLayout = @(
  'texlive\texmfs\install\miktex\config\miktexstartup.ini',
  'texlive\texmfs\config',
  'texlive\texmfs\data'
)
foreach ($relativePath in $portableTeXLayout) {
  if (!(Test-Path -LiteralPath (Join-Path $Dest $relativePath))) {
    throw "Portable MiKTeX layout is incomplete: $relativePath"
  }
}

# Compile a Chinese document with an isolated profile and package installation
# disabled. This prevents a build machine's system MiKTeX from masking an
# incomplete release tree.
$texSmokeRoot = Join-Path $env:TEMP ("vibe-release-tex-{0}" -f $PID)
$texSmokeProfile = Join-Path $texSmokeRoot 'profile'
$savedTexEnvironment = [ordered]@{
  APPDATA = $env:APPDATA
  LOCALAPPDATA = $env:LOCALAPPDATA
  USERPROFILE = $env:USERPROFILE
  HOME = $env:HOME
  MIKTEX_REPOSITORY = $env:MIKTEX_REPOSITORY
}
try {
  New-Item -ItemType Directory -Path $texSmokeProfile -Force | Out-Null
  # Keep the smoke document ASCII-only. Chinese source-file encoding depends on
# how PowerShell loads this script on localized Windows hosts; an ASCII probe
# still forces ctexart/xeCJK/fontspec resolution from the portable tree.
  $texSource = @(
    '\documentclass{ctexart}',
    '\usepackage{amsmath,booktabs,hyperref}',
    '\begin{document}',
    'Offline release acceptance: \(E=mc^2\).',
    '\end{document}',
    ''
  ) -join "`n"
  [IO.File]::WriteAllText(
    (Join-Path $texSmokeRoot 'smoke.tex'),
    $texSource,
    (New-Object System.Text.UTF8Encoding($false))
  )
  $env:APPDATA = Join-Path $texSmokeProfile 'AppData\Roaming'
  $env:LOCALAPPDATA = Join-Path $texSmokeProfile 'AppData\Local'
  $env:USERPROFILE = $texSmokeProfile
  $env:HOME = $texSmokeProfile
  $env:MIKTEX_REPOSITORY = ''
  New-Item -ItemType Directory -Path $env:APPDATA, $env:LOCALAPPDATA -Force | Out-Null
  Push-Location $texSmokeRoot
  try {
    & (Join-Path $Dest $requiredFiles.xelatex) `
      --disable-installer -interaction=nonstopmode -halt-on-error smoke.tex *> compile.log
    $texExitCode = $LASTEXITCODE
  } finally {
    Pop-Location
  }
  $texLogPath = Join-Path $texSmokeRoot 'compile.log'
  $texLog = ''
  if (Test-Path -LiteralPath $texLogPath -PathType Leaf) {
    # XeLaTeX logs contain absolute Unicode paths; force UTF-8 rather than the
    # process ANSI code page so Chinese release-tree paths remain searchable.
    $texLog = [IO.File]::ReadAllText($texLogPath, [Text.Encoding]::UTF8)
    if ([string]::IsNullOrWhiteSpace($texLog)) {
      $texLog = Get-Content -LiteralPath $texLogPath -Raw -ErrorAction SilentlyContinue
    }
  }
  $bundledTeXRoot = [IO.Path]::GetFullPath((Join-Path $Dest 'texlive'))
  $bundledTeXRootAlt = $bundledTeXRoot.Replace('\', '/')
  if ($texExitCode -ne 0 -or !(Test-Path -LiteralPath (Join-Path $texSmokeRoot 'smoke.pdf') -PathType Leaf)) {
    throw "Bundled XeLaTeX offline compile probe failed with exit code $texExitCode`n$texLog"
  }
  $usesBundledTree = (
    $texLog.IndexOf($bundledTeXRoot, [StringComparison]::OrdinalIgnoreCase) -ge 0 -or
    $texLog.IndexOf($bundledTeXRootAlt, [StringComparison]::OrdinalIgnoreCase) -ge 0 -or
    $texLog -match [regex]::Escape(($bundledTeXRoot -replace '\\', '[\\/]')) -or
    $texLog -match 'texmfs[\\/]+install[\\/]+tex'
  )
  $usesSystemMiKTeX = $texLog -match 'AppData[\\/]Local[\\/]Programs[\\/]MiKTeX'
  if ((-not $usesBundledTree) -or $usesSystemMiKTeX) {
    throw "Bundled XeLaTeX probe resolved packages outside the portable runtime`nbundled=$bundledTeXRoot`n$texLog"
  }
} finally {
  foreach ($name in $savedTexEnvironment.Keys) {
    $value = $savedTexEnvironment[$name]
    if ($null -eq $value) {
      Remove-Item -Path "env:$name" -ErrorAction SilentlyContinue
    } else {
      Set-Item -Path "env:$name" -Value $value
    }
  }
  if (Test-Path -LiteralPath $texSmokeRoot) {
    $resolvedSmoke = [IO.Path]::GetFullPath($texSmokeRoot)
    $tempPrefix = [IO.Path]::GetFullPath($env:TEMP).TrimEnd([IO.Path]::DirectorySeparatorChar) + [IO.Path]::DirectorySeparatorChar
    if (!$resolvedSmoke.StartsWith($tempPrefix, [StringComparison]::OrdinalIgnoreCase)) {
      throw "Refusing unsafe TeX smoke cleanup: $resolvedSmoke"
    }
    Remove-Item -LiteralPath $resolvedSmoke -Recurse -Force
  }
}

$stagedPython = Join-Path $Dest $requiredFiles.python
$utf8NoBom = New-Object System.Text.UTF8Encoding($false)
$probe = @'
import importlib
modules = [
    "fastapi", "uvicorn", "aiosqlite", "cryptography", "websockets",
    "watchfiles", "watchdog", "PIL", "pymupdf", "fitz", "PyPDF2",
    "pypdf", "docx", "lxml", "numpy", "scipy", "pandas",
    "matplotlib", "seaborn", "openpyxl", "charset_normalizer", "requests",
]
for name in modules:
    importlib.import_module(name)
print("runtime-python-imports-ok")
'@
$probePath = Join-Path $env:TEMP ("vibe-runtime-probe-{0}.py" -f $PID)
try {
  [IO.File]::WriteAllText($probePath, $probe, $utf8NoBom)
  $probeOutput = & $stagedPython -X utf8 $probePath
  if ($LASTEXITCODE -ne 0 -or $probeOutput -notcontains 'runtime-python-imports-ok') {
    throw "Staged Python dependency import probe failed: $probeOutput"
  }
} finally {
  Remove-Item -LiteralPath $probePath -Force -ErrorAction SilentlyContinue
}

function Get-VersionLine([string]$Executable, [string[]]$Arguments) {
  try {
    $output = & $Executable @Arguments 2>$null
    if ($LASTEXITCODE -eq 0 -and $output) {
      return [string]($output | Select-Object -First 1)
    }
  } catch {}
  return (Get-Item -LiteralPath $Executable).VersionInfo.ProductVersion
}

function Get-RequiredVersionLine([string]$Executable) {
  try {
    $output = & $Executable '--version' 2>&1
  } catch {
    throw "Executable version probe failed for $Executable`: $($_.Exception.Message)"
  }
  if ($LASTEXITCODE -ne 0 -or !$output) {
    throw "Executable version probe failed for $Executable with exit code $LASTEXITCODE"
  }
  return [string]($output | Select-Object -First 1)
}

function New-Capability([string]$RelativePath, [string]$Version, [string]$License) {
  $file = Join-Path $Dest $RelativePath
  return [ordered]@{
    path = $RelativePath.Replace('\', '/')
    version = $Version
    sha256 = (Get-FileHash -LiteralPath $file -Algorithm SHA256).Hash.ToLowerInvariant()
    bytes = (Get-Item -LiteralPath $file).Length
    license = $License
  }
}

$capabilities = [ordered]@{
  python = New-Capability $requiredFiles.python (Get-VersionLine (Join-Path $Dest $requiredFiles.python) @('--version')) 'PSF-2.0'
  node = New-Capability $requiredFiles.node (Get-VersionLine (Join-Path $Dest $requiredFiles.node) @('--version')) 'MIT'
  codex = New-Capability $requiredFiles.codex (Get-RequiredVersionLine (Join-Path $Dest $requiredFiles.codex)) 'Apache-2.0'
  ripgrep = New-Capability $requiredFiles.ripgrep (Get-RequiredVersionLine (Join-Path $Dest $requiredFiles.ripgrep)) 'MIT OR Unlicense'
  git = New-Capability $requiredFiles.git (Get-VersionLine (Join-Path $Dest $requiredFiles.git) @('--version')) 'GPL-2.0-only'
  bash = New-Capability $requiredFiles.bash (Get-VersionLine (Join-Path $Dest $requiredFiles.bash) @('--version')) 'GPL-3.0-or-later'
  pandoc = New-Capability $requiredFiles.pandoc (Get-VersionLine (Join-Path $Dest $requiredFiles.pandoc) @('--version')) 'GPL-2.0-or-later'
  drawio = New-Capability $requiredFiles.drawio ((Get-Item -LiteralPath (Join-Path $Dest $requiredFiles.drawio)).VersionInfo.ProductVersion) 'Apache-2.0'
  xelatex = New-Capability $requiredFiles.xelatex ((Get-Item -LiteralPath (Join-Path $Dest $requiredFiles.xelatex)).VersionInfo.ProductVersion) 'GPL-2.0-or-later'
  pdflatex = New-Capability $requiredFiles.pdflatex ((Get-Item -LiteralPath (Join-Path $Dest $requiredFiles.pdflatex)).VersionInfo.ProductVersion) 'GPL-2.0-or-later'
  latexmk = New-Capability $requiredFiles.latexmk ((Get-Item -LiteralPath (Join-Path $Dest $requiredFiles.latexmk)).VersionInfo.ProductVersion) 'GPL-2.0-or-later'
  biber = New-Capability $requiredFiles.biber ((Get-Item -LiteralPath (Join-Path $Dest $requiredFiles.biber)).VersionInfo.ProductVersion) 'Artistic-2.0'
}

if ($capabilities.codex.version -ne "codex-cli $($codexLock.version)") {
  throw "Codex executable reports an unexpected version: $($capabilities.codex.version)"
}
if ($capabilities.ripgrep.version -notmatch '^ripgrep 15\.1\.0(?: \(rev [0-9a-f]+\))?$') {
  throw "Codex-bundled ripgrep reports an unexpected version: $($capabilities.ripgrep.version)"
}

function New-LicenseRecord([string]$RelativePath) {
  $licensePath = Join-Path $Dest $RelativePath
  if (!(Test-Path -LiteralPath $licensePath -PathType Leaf)) {
    throw "Agent CLI license file is missing: $RelativePath"
  }
  return [ordered]@{
    path = $RelativePath.Replace('\', '/')
    sha256 = (Get-FileHash -LiteralPath $licensePath -Algorithm SHA256).Hash.ToLowerInvariant()
    bytes = (Get-Item -LiteralPath $licensePath).Length
  }
}

$cliLockHash = (Get-FileHash -LiteralPath $CliLockPath -Algorithm SHA256).Hash.ToLowerInvariant()
$agentCliManifest = [ordered]@{
  schema_version = '1.0'
  target = $CliLock.target
  registry = $CliLock.registry
  lock_sha256 = $cliLockHash
  credential_material_included = $false
  release_eligible = $releaseEligible
  release_blockers = @($releaseBlockers)
  build_purpose = if ($LocalValidationOnly) { 'local_validation_only' } else { 'redistributable_release' }
  adapters = [ordered]@{
    codex = [ordered]@{
      executable = $capabilities.codex.path
      reported_version = $capabilities.codex.version
      sha256 = $capabilities.codex.sha256
      bytes = $capabilities.codex.bytes
      npm_package = $codexLock.npm_package
      package_version = $codexLock.version
      package_integrity = $codexLock.integrity
      platform_package = $codexLock.platform_package
      platform_registry_package = $codexLock.platform_registry_package
      platform_version = $codexLock.platform_version
      platform_integrity = $codexLock.platform_integrity
      install_mode = $codexLock.install_mode
      license = $codexLock.license
      redistribution_status = $codexLock.redistribution_status
      license_files = @(
        (New-LicenseRecord 'agents\codex\LICENSE'),
        (New-LicenseRecord 'agents\codex\NOTICE')
      )
      bundled_components = @(
        [ordered]@{
          name = 'ripgrep'
          version = $capabilities.ripgrep.version
          executable = $capabilities.ripgrep.path
          sha256 = $capabilities.ripgrep.sha256
          bytes = $capabilities.ripgrep.bytes
          license = 'MIT OR Unlicense'
          source = 'https://github.com/BurntSushi/ripgrep/tree/15.1.0'
          license_files = @(
            (New-LicenseRecord 'agents\codex\ripgrep\COPYING'),
            (New-LicenseRecord 'agents\codex\ripgrep\LICENSE-MIT'),
            (New-LicenseRecord 'agents\codex\ripgrep\UNLICENSE')
          )
        }
      )
    }
  }
  external_adapters = $externalAdapters
}

$utf8NoBom = New-Object System.Text.UTF8Encoding($false)
[IO.File]::WriteAllText(
  (Join-Path $Dest 'agent-cli-manifest.json'),
  ($agentCliManifest | ConvertTo-Json -Depth 8),
  $utf8NoBom
)

$inventoryScript = @'
import importlib.metadata as metadata, json
names = [
    "fastapi", "uvicorn", "aiosqlite", "cryptography", "websockets",
    "watchfiles", "watchdog", "Pillow", "PyMuPDF", "PyPDF2", "pypdf",
    "python-docx", "lxml", "numpy", "scipy", "pandas", "matplotlib",
    "seaborn", "openpyxl", "requests", "PyYAML",
]
items = []
for name in names:
    dist = metadata.distribution(name)
    info = dist.metadata
    license_id = info.get("License-Expression") or "NOASSERTION"
    items.append({"name": info.get("Name") or name, "version": dist.version, "license": license_id})
print(json.dumps(items, ensure_ascii=False, separators=(",", ":")))
'@
$inventoryPath = Join-Path $env:TEMP ("vibe-runtime-inventory-{0}.py" -f $PID)
try {
  [IO.File]::WriteAllText($inventoryPath, $inventoryScript, $utf8NoBom)
  $pythonPackagesJson = & $stagedPython -X utf8 $inventoryPath
  if ($LASTEXITCODE -ne 0) {
    throw 'Unable to inventory staged Python distributions'
  }
} finally {
  Remove-Item -LiteralPath $inventoryPath -Force -ErrorAction SilentlyContinue
}
$pythonPackages = New-Object System.Collections.ArrayList
foreach ($package in ($pythonPackagesJson | ConvertFrom-Json)) {
  [void]$pythonPackages.Add($package)
}

$files = @(Get-ChildItem -LiteralPath $Dest -Recurse -File)
$manifest = [ordered]@{
  schema_version = '1.2'
  generated_at_utc = [DateTime]::UtcNow.ToString('o')
  layout = 'portable-windows-x64'
  release_eligible = $releaseEligible
  release_blockers = @($releaseBlockers)
  build_purpose = if ($LocalValidationOnly) { 'local_validation_only' } else { 'redistributable_release' }
  files = $files.Count
  bytes = ($files | Measure-Object Length -Sum).Sum
  capabilities = $capabilities
  agent_clis = $agentCliManifest.adapters
  external_adapters = $externalAdapters
  agent_cli_manifest_sha256 = (Get-FileHash -LiteralPath (Join-Path $Dest 'agent-cli-manifest.json') -Algorithm SHA256).Hash.ToLowerInvariant()
  licenses = @(
    (New-LicenseRecord 'python\LICENSE.txt'),
    (New-LicenseRecord 'node\LICENSE'),
    (New-LicenseRecord 'agents\codex\LICENSE'),
    (New-LicenseRecord 'agents\codex\NOTICE'),
    (New-LicenseRecord 'agents\codex\ripgrep\COPYING'),
    (New-LicenseRecord 'agents\codex\ripgrep\LICENSE-MIT'),
    (New-LicenseRecord 'agents\codex\ripgrep\UNLICENSE')
  )
  python_packages = $pythonPackages
  sha256 = @($files | ForEach-Object {
    [ordered]@{
      path = $_.FullName.Substring($Dest.Length + 1).Replace('\', '/')
      sha256 = (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
      bytes = $_.Length
    }
  })
}

[IO.File]::WriteAllText(
  (Join-Path $Dest 'manifest.json'),
  ($manifest | ConvertTo-Json -Depth 8),
  $utf8NoBom
)
$manifestSummary = [ordered]@{
  schema_version = $manifest.schema_version
  manifest_sha256 = (Get-FileHash -LiteralPath (Join-Path $Dest 'manifest.json') -Algorithm SHA256).Hash.ToLowerInvariant()
  generated_at_utc = $manifest.generated_at_utc
  layout = $manifest.layout
  release_eligible = $manifest.release_eligible
  release_blockers = $manifest.release_blockers
  build_purpose = $manifest.build_purpose
  files = $manifest.files
  bytes = $manifest.bytes
  capabilities = $manifest.capabilities
  agent_clis = $manifest.agent_clis
  external_adapters = $manifest.external_adapters
  agent_cli_manifest_sha256 = $manifest.agent_cli_manifest_sha256
  licenses = $manifest.licenses
  python_packages = $manifest.python_packages
}
[IO.File]::WriteAllText(
  (Join-Path $Dest 'manifest.summary.json'),
  ($manifestSummary | ConvertTo-Json -Depth 8),
  $utf8NoBom
)

Exit-StageMutex
[ordered]@{
  schema_version = $manifest.schema_version
  files = $manifest.files
  bytes = $manifest.bytes
  capabilities = @($capabilities.Keys)
  python_packages = $pythonPackages.Count
} | ConvertTo-Json -Depth 4
