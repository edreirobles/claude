Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$repoRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot "..\.."))
$logsDir = Join-Path $repoRoot "logs"
$supervisorLog = Join-Path $logsDir "autostart-supervisor.log"
$stdoutLog = Join-Path $logsDir "autostart-uvicorn.out.log"
$stderrLog = Join-Path $logsDir "autostart-uvicorn.err.log"
$runnerScript = Join-Path $PSScriptRoot "run-uvicorn.ps1"
$mutexName = "Global\XToLinkedInSupervisor"
$restartDelaySeconds = 10
$pollDelaySeconds = 15
$bootGraceSeconds = 90
$healthCheckUrl = "http://127.0.0.1:8000/health"
$healthTimeoutSeconds = 5
$maxConsecutiveUnhealthyChecks = 4

if (-not (Test-Path $logsDir)) {
    New-Item -ItemType Directory -Path $logsDir | Out-Null
}

function Write-SupervisorLog {
    param([string]$Message)
    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    Add-Content -LiteralPath $supervisorLog -Value "[$timestamp] $Message"
}

function Get-PythonExecutable {
    $command = Get-Command python -ErrorAction SilentlyContinue
    if ($command -and (Test-Path $command.Source)) {
        return $command.Source
    }

    $fallbacks = @(
        "C:\Users\victo\AppData\Local\Programs\Python\Python312\python.exe",
        "C:\Python312\python.exe"
    )

    foreach ($candidate in $fallbacks) {
        if (Test-Path $candidate) {
            return $candidate
        }
    }

    throw "No encontré python.exe para arrancar la app."
}

function Get-BootUptimeSeconds {
    try {
        $os = Get-CimInstance Win32_OperatingSystem
        $bootAt = [Management.ManagementDateTimeConverter]::ToDateTime($os.LastBootUpTime)
        return [int][Math]::Floor((New-TimeSpan -Start $bootAt -End (Get-Date)).TotalSeconds)
    }
    catch {
        Write-SupervisorLog "No se pudo calcular el uptime del sistema: $($_.Exception.Message)"
        return $null
    }
}

function Get-UvicornProcesses {
    $processes = Get-CimInstance Win32_Process -Filter "name='python.exe'"
    $matches = @()
    foreach ($process in $processes) {
        $line = $process.CommandLine
        if ($line -and $line -like "*-m uvicorn app.main:app*") {
            $matches += $process
        }
    }
    return $matches
}

function Start-UvicornProcess {
    param(
        [string]$PythonPath
    )

    if (-not (Test-Path $runnerScript)) {
        throw "No encontré el runner de uvicorn en $runnerScript"
    }

    $process = Start-Process `
        -FilePath "powershell.exe" `
        -ArgumentList @(
            "-NoProfile",
            "-ExecutionPolicy", "Bypass",
            "-WindowStyle", "Hidden",
            "-File", $runnerScript,
            "-PythonPath", $PythonPath
        ) `
        -WorkingDirectory $repoRoot `
        -WindowStyle Hidden `
        -PassThru

    Write-SupervisorLog "Runner de uvicorn lanzado. PID=$($process.Id)"
}

function Test-AppHealthy {
    try {
        $response = Invoke-RestMethod -Uri $healthCheckUrl -Method Get -TimeoutSec $healthTimeoutSeconds
        return $response.status -eq "ok"
    }
    catch {
        return $false
    }
}

function Stop-UvicornProcesses {
    $processes = @(Get-UvicornProcesses)
    if ($processes.Count -eq 0) {
        return
    }

    $ids = $processes | Select-Object -ExpandProperty ProcessId -Unique
    Write-SupervisorLog ("Deteniendo procesos uvicorn no saludables: " + (($ids | Sort-Object) -join ", "))

    foreach ($id in ($ids | Sort-Object -Descending)) {
        try {
            Stop-Process -Id $id -Force -ErrorAction Stop
        }
        catch {
            Write-SupervisorLog "No se pudo detener el proceso ${id}: $($_.Exception.Message)"
        }
    }
}

$pythonExe = Get-PythonExecutable
$mutex = New-Object System.Threading.Mutex($false, $mutexName)
$lockTaken = $false
$unhealthyChecks = 0

try {
    $lockTaken = $mutex.WaitOne(0, $false)
    if (-not $lockTaken) {
        Write-SupervisorLog "Ya hay otro supervisor activo. Este proceso termina."
        exit 0
    }

    Write-SupervisorLog "Supervisor iniciado. Repo: $repoRoot"

    $bootUptimeSeconds = Get-BootUptimeSeconds
    if ($bootUptimeSeconds -ne $null -and $bootUptimeSeconds -lt $bootGraceSeconds) {
        $remaining = $bootGraceSeconds - $bootUptimeSeconds
        Write-SupervisorLog "Windows llevaba $bootUptimeSeconds s desde el arranque. Esperando $remaining s antes de supervisar la app."
        Start-Sleep -Seconds $remaining
    }

    Push-Location $repoRoot
    try {
        while ($true) {
            $uvicornProcesses = @(Get-UvicornProcesses)
            if ($uvicornProcesses.Count -gt 0) {
                if (Test-AppHealthy) {
                    $unhealthyChecks = 0
                    Start-Sleep -Seconds $pollDelaySeconds
                    continue
                }

                $unhealthyChecks += 1
                Write-SupervisorLog "Health check falló (intento $unhealthyChecks de $maxConsecutiveUnhealthyChecks)."

                if ($unhealthyChecks -lt $maxConsecutiveUnhealthyChecks) {
                    Start-Sleep -Seconds $pollDelaySeconds
                    continue
                }

                Stop-UvicornProcesses
                $unhealthyChecks = 0
                Start-Sleep -Seconds $restartDelaySeconds
                continue
            }

            $unhealthyChecks = 0
            Write-SupervisorLog "No detecté la app corriendo. Arrancando uvicorn."
            Start-UvicornProcess -PythonPath $pythonExe
            Start-Sleep -Seconds $restartDelaySeconds
        }
    }
    finally {
        Pop-Location
    }
}
finally {
    if ($lockTaken) {
        $mutex.ReleaseMutex() | Out-Null
    }
    $mutex.Dispose()
}
