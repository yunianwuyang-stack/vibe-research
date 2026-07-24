[CmdletBinding()]
param([Parameter(Mandatory=$true)][string]$Executable)
$ErrorActionPreference='Stop'
$Root=Split-Path -Parent $PSScriptRoot
$Cache=Join-Path $env:LOCALAPPDATA 'electron-builder\Cache\winCodeSign'
$Rcedit=Get-ChildItem $Cache -Recurse -File -Filter rcedit-x64.exe -ErrorAction SilentlyContinue | Select-Object -First 1 -ExpandProperty FullName
if(!$Rcedit){throw 'rcedit-x64.exe is unavailable; Windows identity cannot be produced'}
$Version=(Get-Content (Join-Path $Root 'package.json') -Raw -Encoding UTF8|ConvertFrom-Json).version
& $Rcedit $Executable --set-version-string ProductName 'Vibe Research' --set-version-string FileDescription 'Vibe Research' --set-version-string CompanyName 'Vibe Research Project' --set-version-string InternalName 'Vibe Research' --set-version-string OriginalFilename 'Vibe Research.exe' --set-file-version $Version --set-product-version $Version --set-icon (Join-Path $Root 'icon.ico')
if($LASTEXITCODE -ne 0){throw "rcedit failed: $LASTEXITCODE"}
