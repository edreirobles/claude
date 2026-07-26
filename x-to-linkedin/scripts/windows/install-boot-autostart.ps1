Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$repoRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot "..\.."))
$logsDir = Join-Path $repoRoot "logs"
$installLog = Join-Path $logsDir "boot-autostart-install.log"

if (-not (Test-Path $logsDir)) {
    New-Item -ItemType Directory -Path $logsDir | Out-Null
}

function Write-InstallLog {
    param([string]$Message)
    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    Add-Content -LiteralPath $installLog -Value "[$timestamp] $Message"
}

function Test-IsAdministrator {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($identity)
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

if (-not (Test-IsAdministrator)) {
    Write-InstallLog "Sesion sin privilegios de administrador. Intentando elevacion UAC."
    Start-Process `
        -FilePath "powershell.exe" `
        -Verb RunAs `
        -ArgumentList @(
            "-NoProfile",
            "-ExecutionPolicy", "Bypass",
            "-File", "`"$PSCommandPath`""
        ) | Out-Null
    Write-Output "Se abrio la ventana de seguridad de Windows."
    Write-Output "Debes hacer clic en 'Si' en esa ventana."
    Write-Output "No se responde escribiendo y/si/yes en esta consola."
    exit 0
}

$supervisorScript = Join-Path $PSScriptRoot "start-supervisor.ps1"
$taskName = "XToLinkedIn Boot AutoStart"

if (-not (Test-Path $supervisorScript)) {
    Write-InstallLog "No se encontro el supervisor: $supervisorScript"
    throw "No encontré el supervisor en $supervisorScript"
}

$action = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$supervisorScript`""

$trigger = New-ScheduledTaskTrigger -AtStartup

$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable

$principal = New-ScheduledTaskPrincipal `
    -UserId "SYSTEM" `
    -LogonType ServiceAccount `
    -RunLevel Highest

Register-ScheduledTask `
    -TaskName $taskName `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Principal $principal `
    -Description "Arranca y supervisa X to LinkedIn desde el arranque de Windows, sin requerir login." `
    -Force | Out-Null

Start-ScheduledTask -TaskName $taskName
Write-InstallLog "Task '$taskName' registrada y arrancada."
Write-Output "Task '$taskName' registrada y arrancada."
