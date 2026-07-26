Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$repoRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot "..\.."))
$supervisorScript = Join-Path $PSScriptRoot "start-supervisor.ps1"
$taskName = "XToLinkedIn AutoStart"
$currentUser = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
$startupDir = [Environment]::GetFolderPath("Startup")
$startupCmd = Join-Path $startupDir "XToLinkedIn AutoStart.cmd"

if (-not (Test-Path $supervisorScript)) {
    throw "No encontré el supervisor en $supervisorScript"
}

$action = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$supervisorScript`""

$triggers = @(
    (New-ScheduledTaskTrigger -AtLogOn -User $currentUser)
)

$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable

$principal = New-ScheduledTaskPrincipal `
    -UserId $currentUser `
    -LogonType Interactive `
    -RunLevel Highest

try {
    Register-ScheduledTask `
        -TaskName $taskName `
        -Action $action `
        -Trigger $triggers `
        -Settings $settings `
        -Principal $principal `
        -Description "Arranca y supervisa X to LinkedIn despues de iniciar sesion en Windows." `
        -Force | Out-Null

    Write-Output "Task '$taskName' registrada para $currentUser."
}
catch {
    $startupContents = @(
        "@echo off",
        "powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$supervisorScript`""
    )
    Set-Content -LiteralPath $startupCmd -Value $startupContents -Encoding ASCII
    Write-Output "No pude registrar la task por permisos. Dejé fallback en Startup: $startupCmd"
}
