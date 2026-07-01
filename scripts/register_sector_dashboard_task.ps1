$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $PSScriptRoot
$TaskName = "SectorMomentumDashboardDailyUpdate"
$UpdateScript = Join-Path $Root "scripts\update_sector_dashboard.ps1"

$Action = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$UpdateScript`""

$Trigger = New-ScheduledTaskTrigger -Daily -At 17:00
$Settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $Action `
    -Trigger $Trigger `
    -Settings $Settings `
    -Description "Daily 17:00 Beijing-time sector momentum dashboard update and GitHub Pages deployment with safe single-threaded data access." `
    -Force

Write-Host "Registered scheduled task: $TaskName"
