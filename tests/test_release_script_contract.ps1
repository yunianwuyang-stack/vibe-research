$s=Get-Content -Raw scripts/Build-Release.ps1
if($s -notmatch 'No NSIS installer was produced'){throw 'installer failure guard missing'}
if($s -notmatch 'ELECTRON_MIRROR'){throw 'HTTPS Electron mirror guard missing'}
if($s -notmatch 'Assert-ReleasePayloadPolicy'){throw 'release payload policy guard missing'}
if($s -notmatch 'npm\.cmd ci'){throw 'root dependency lock install missing'}
if($s -notmatch 'DeliveryName\s*='){throw 'delivery target missing'}
if($s -notmatch 'asar = \$true'){throw 'release manifest must record ASAR protection'}
if($s -notmatch '(?s)Push-Location \$Root\s*try \{\s*npm\.cmd exec electron-builder'){throw 'electron-builder packaging must run from the product root'}
if($s -notmatch '0x6700' -or $s -notmatch '0x5efa'){throw 'delivery path must be encoding-independent under Windows PowerShell'}
Write-Output 'release guard OK'
