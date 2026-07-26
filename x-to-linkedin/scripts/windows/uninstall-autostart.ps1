Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$taskName = "XToLinkedIn AutoStart"
$startupDir = [Environment]::GetFolderPath("Startup")
$startupCmd = Join-Path $startupDir "XToLinkedIn AutoStart.cmd"

if (Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue) {
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
    Write-Output "Task '$taskName' eliminada."
}
else {
    Write-Output "La task '$taskName' no existe."
}

if (Test-Path $startupCmd) {
    Remove-Item -LiteralPath $startupCmd -Force
    Write-Output "Fallback de Startup eliminado."
}
