$ErrorActionPreference = 'Stop'
$taskProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$taskLocal = Join-Path $taskProjectRoot '.local'
$taskPidPath = Join-Path $taskLocal 'processes.json'
if (Test-Path -LiteralPath $taskPidPath) {
    $taskEntries = Get-Content -LiteralPath $taskPidPath -Raw | ConvertFrom-Json
    foreach ($taskProperty in $taskEntries.PSObject.Properties) {
        $taskEntry = $taskProperty.Value
        $taskProcess = Get-Process -Id $taskEntry.id -ErrorAction SilentlyContinue
        $taskStarted = if ($taskEntry.started -is [DateTime]) { $taskEntry.started.ToUniversalTime() } else { ([DateTimeOffset]::Parse([string]$taskEntry.started)).UtcDateTime }
        if ($taskProcess -and [Math]::Abs(($taskProcess.StartTime.ToUniversalTime() - $taskStarted).TotalSeconds) -lt 1) {
            # Only the recorded process tree is stopped; start time guards against PID reuse.
            & taskkill.exe /PID $taskProcess.Id /T /F | Out-Null
        }
    }
    Remove-Item -LiteralPath $taskPidPath
}
$taskPgData = Join-Path $taskLocal 'pgdata'
$taskPgCtl = Join-Path $taskLocal 'tools\pgsql\bin\pg_ctl.exe'
if (Test-Path -LiteralPath (Join-Path $taskPgData 'postmaster.pid')) {
    & $taskPgCtl -D $taskPgData -m fast -w stop
}
Write-Output 'Project services stopped. Database and uploaded files are preserved.'
