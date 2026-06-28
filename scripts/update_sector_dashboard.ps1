$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $PSScriptRoot
$Python = "C:\Users\AERO\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
$Script = Join-Path $Root "sector_dashboard.py"
$Output = Join-Path $Root "output\sector_dashboard\index.html"

Set-Location $Root
& $Python $Script --output $Output
