[CmdletBinding()]
param()
$ErrorActionPreference='Stop'
$Root=Split-Path -Parent $PSScriptRoot
& (Join-Path $PSScriptRoot 'Test-ProductIdentity.ps1') | Out-Null
$manifest=Get-Content (Join-Path $Root 'runtime-manifest.json') -Raw -Encoding UTF8|ConvertFrom-Json
$installer=Join-Path $Root "release\$($manifest.installer.path)"
$unpacked=Join-Path $Root $manifest.unpacked_executable.path.Replace('/','\')
if((Get-FileHash $installer).Hash -ne $manifest.installer.sha256){throw 'Installer manifest hash mismatch'}
if((Get-FileHash $unpacked).Hash -ne $manifest.unpacked_executable.sha256){throw 'Unpacked executable manifest hash mismatch'}
if($manifest.code_signing -ne 'blocked_external_certificate_required' -or $manifest.installer.code_signing -ne 'NotSigned'){throw 'Signing state is not reported truthfully'}
$config=Get-Content (Join-Path $Root 'updater-config.json') -Raw -Encoding UTF8|ConvertFrom-Json
if($config.enabled -ne $false -or $null -ne $config.server_url){throw 'Remote updates must be disabled by default'}
$delivery=[IO.Path]::Combine((Split-Path $Root -Parent),'最新版构建')
if((Get-FileHash (Join-Path $delivery 'Vibe Research.exe')).Hash -ne (Get-FileHash $unpacked).Hash){throw 'Delivery executable mismatch'}
if((Get-FileHash (Join-Path $delivery $manifest.installer.path)).Hash -ne (Get-FileHash $installer).Hash){throw 'Delivery installer mismatch'}
[ordered]@{verdict='PASS';product='Vibe Research';manifest_commit=$manifest.product_commit;installer_sha256=$manifest.installer.sha256;unpacked_sha256=$manifest.unpacked_executable.sha256;updates='disabled';signing='NotSigned/external-block';delivery_mapping=$true}|ConvertTo-Json -Compress
