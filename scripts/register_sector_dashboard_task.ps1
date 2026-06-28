$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $PSScriptRoot
$TaskName = "SectorMomentumDashboardDailyUpdate"
$UpdateScript = Join-Path $Root "scripts\update_sector_dashboard.ps1"

$Action = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$UpdateScript`""

$Trigger = New-ScheduledTaskTrigger -Daily -At 16:30
$Settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $Action `
    -Trigger $Trigger `
    -Settings $Settings `
    -Description "Daily sector momentum dashboard update with safe single-threaded data access." `
    -Force

Write-Host "Registered scheduled task: $TaskName"
