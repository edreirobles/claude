param(
    [Parameter(Mandatory = $true)]
    [string]$PythonPath
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$repoRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot "..\.."))
$logsDir = Join-Path $repoRoot "logs"
$supervisorLog = Join-Path $logsDir "autostart-supervisor.log"
$stdoutLog = Join-Path $logsDir "autostart-uvicorn.out.log"
$stderrLog = Join-Path $logsDir "autostart-uvicorn.err.log"
$playwrightBrowsersPath = "C:\Users\victo\AppData\Local\ms-playwright"

if (-not (Test-Path $logsDir)) {
    New-Item -ItemType Directory -Path $logsDir | Out-Null
}

function Write-RunnerLog {
    param([string]$Message)
    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    Add-Content -LiteralPath $supervisorLog -Value "[$timestamp] $Message"
}

Write-RunnerLog "Runner de uvicorn iniciado. Python=$PythonPath"

if (Test-Path $playwrightBrowsersPath) {
    $env:PLAYWRIGHT_BROWSERS_PATH = $playwrightBrowsersPath
    Write-RunnerLog "Playwright browsers path=$playwrightBrowsersPath"
}
else {
    Write-RunnerLog "Playwright browsers path no encontrado en $playwrightBrowsersPath"
}

try {
    $process = Start-Process `
        -FilePath $PythonPath `
        -ArgumentList @(
            "-m",
            "uvicorn",
            "app.main:app",
            "--host",
            "0.0.0.0",
            "--port",
            "8000"
        ) `
        -WorkingDirectory $repoRoot `
        -RedirectStandardOutput $stdoutLog `
        -RedirectStandardError $stderrLog `
        -PassThru

    Write-RunnerLog "Proceso uvicorn lanzado. PID=$($process.Id)"
    $process.WaitForExit()
    Write-RunnerLog "Proceso uvicorn terminó con código $($process.ExitCode)"
}
catch {
    Write-RunnerLog "Runner de uvicorn falló: $($_.Exception.Message)"
    throw
}
