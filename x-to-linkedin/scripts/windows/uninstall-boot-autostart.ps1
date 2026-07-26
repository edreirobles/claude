Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$taskName = "XToLinkedIn Boot AutoStart"

if (Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue) {
    Stop-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
    Write-Output "Task '$taskName' eliminada."
}
else {
    Write-Output "La task '$taskName' no existe."
}
