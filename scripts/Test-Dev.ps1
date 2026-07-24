param([switch]$Install)
$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot
$Venv = Join-Path $Root '.venv-dev'
$Python = Join-Path $Venv 'Scripts\python.exe'
if (!(Test-Path $Python)) { py -3.12 -m venv $Venv }
if ($Install) { & $Python -m pip install -r (Join-Path $Root 'requirements-dev.txt') }
$env:PYTHONPATH = Join-Path $Root 'backend'
& $Python -m pytest -q (Join-Path $Root 'tests')
& $Python -m ruff check (Join-Path $Root 'backend')
