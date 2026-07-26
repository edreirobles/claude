Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$repoRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot "..\.."))
$logsDir = Join-Path $repoRoot "logs"
$restartLog = Join-Path $logsDir "boot-autostart-restart.log"
$taskName = "XToLinkedIn Boot AutoStart"

if (-not (Test-Path $logsDir)) {
    New-Item -ItemType Directory -Path $logsDir | Out-Null
}

function Write-RestartLog {
    param([string]$Message)
    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    Add-Content -LiteralPath $restartLog -Value "[$timestamp] $Message"
}

function Test-IsAdministrator {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($identity)
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

if (-not (Test-IsAdministrator)) {
    Write-RestartLog "Sesion sin privilegios de administrador. Intentando elevacion UAC."
    Start-Process `
        -FilePath "powershell.exe" `
        -Verb RunAs `
        -ArgumentList @(
            "-NoProfile",
            "-ExecutionPolicy", "Bypass",
            "-File", "`"$PSCommandPath`""
        ) | Out-Null
    Write-Output "Se abrio la ventana de seguridad de Windows."
    Write-Output "Haz clic en 'Si' para reiniciar la app elevada."
    exit 0
}

Write-RestartLog "Reinicio solicitado para '$taskName'."

try {
    Stop-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
    Write-RestartLog "Task detenida o no estaba corriendo."
}
catch {
    Write-RestartLog "No se pudo detener la task: $($_.Exception.Message)"
}

Start-Sleep -Seconds 3

$listeners = @(Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue)
foreach ($listener in $listeners) {
    $pid = [int]$listener.OwningProcess
    if ($pid -gt 0) {
        try {
            Stop-Process -Id $pid -Force -ErrorAction Stop
            Write-RestartLog "Proceso en puerto 8000 detenido. PID=$pid"
        }
        catch {
            Write-RestartLog "No se pudo detener PID=${pid}: $($_.Exception.Message)"
        }
    }
}

Start-Sleep -Seconds 2

Start-ScheduledTask -TaskName $taskName
Write-RestartLog "Task arrancada."
Write-Output "App reiniciada. Espera 20-30 segundos y abre http://localhost:8000"
