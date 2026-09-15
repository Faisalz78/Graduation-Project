param(
    [ValidateSet('127.0.0.1', '0.0.0.0')]
    [string]$ApiHost = '127.0.0.1'
)

$ErrorActionPreference = 'Stop'
$taskProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$taskLocal = Join-Path $taskProjectRoot '.local'
$taskBackend = Join-Path $taskProjectRoot '04_Source_Code\backend'
$taskWeb = Join-Path $taskProjectRoot '04_Source_Code\web'
$taskPython = Join-Path $taskBackend '.venv\Scripts\python.exe'
$taskNode = (Get-Command node.exe -ErrorAction Stop).Source
& $taskPython (Join-Path $PSScriptRoot 'bootstrap_local.py')
if ($LASTEXITCODE -ne 0) { throw 'Database startup failed. Inspect .local/bootstrap.log.' }
& (Join-Path $PSScriptRoot 'ensure-local-vision.ps1')

function Test-TaskService([string]$Address) {
    try { return (Invoke-WebRequest -UseBasicParsing -Uri $Address -TimeoutSec 2).StatusCode -eq 200 } catch { return $false }
}

$taskProcesses = @{}
$taskPidPath = Join-Path $taskLocal 'processes.json'
if (Test-Path -LiteralPath $taskPidPath) {
    $taskSaved = Get-Content -LiteralPath $taskPidPath -Raw | ConvertFrom-Json
    foreach ($taskProperty in $taskSaved.PSObject.Properties) {
        $taskProcesses[$taskProperty.Name] = $taskProperty.Value
    }
}
if (-not (Test-TaskService 'http://127.0.0.1:8000/api/v1/health')) {
    $taskProcess = Start-Process -FilePath $taskPython -ArgumentList @('-m', 'uvicorn', 'app.main:app', '--host', $ApiHost, '--port', '8000') -WorkingDirectory $taskBackend -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $taskLocal 'api.stdout.log') -RedirectStandardError (Join-Path $taskLocal 'api.stderr.log')
    $taskProcesses.api = @{ id = $taskProcess.Id; started = $taskProcess.StartTime.ToUniversalTime().ToString('O') }
}
if (-not (Test-TaskService 'http://127.0.0.1:3000/login')) {
    $taskNext = Join-Path $taskWeb 'node_modules\next\dist\bin\next'
    $taskProcess = Start-Process -FilePath $taskNode -ArgumentList @(('"' + $taskNext + '"'), 'dev', '--hostname', '127.0.0.1', '--port', '3000') -WorkingDirectory $taskWeb -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $taskLocal 'web.stdout.log') -RedirectStandardError (Join-Path $taskLocal 'web.stderr.log')
    $taskProcesses.web = @{ id = $taskProcess.Id; started = $taskProcess.StartTime.ToUniversalTime().ToString('O') }
}
$taskWorkerRunning = $false
if ($taskProcesses.ContainsKey('extraction')) {
    $taskEntry = $taskProcesses.extraction
    $taskExisting = Get-Process -Id $taskEntry.id -ErrorAction SilentlyContinue
    if ($taskExisting) {
        $taskExpected = if ($taskEntry.started -is [DateTime]) { $taskEntry.started.ToUniversalTime() } else { ([DateTimeOffset]::Parse([string]$taskEntry.started)).UtcDateTime }
        $taskWorkerRunning = [Math]::Abs(($taskExisting.StartTime.ToUniversalTime() - $taskExpected).TotalSeconds) -lt 1
    }
}
if (-not $taskWorkerRunning) {
    $taskProcess = Start-Process -FilePath $taskPython -ArgumentList @('-m', 'app.extraction_worker') -WorkingDirectory $taskBackend -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $taskLocal 'extraction.stdout.log') -RedirectStandardError (Join-Path $taskLocal 'extraction.stderr.log')
    $taskProcesses.extraction = @{ id = $taskProcess.Id; started = $taskProcess.StartTime.ToUniversalTime().ToString('O') }
}
$taskProcesses | ConvertTo-Json | Set-Content -LiteralPath $taskPidPath -Encoding UTF8
$taskReady = $false
for ($taskAttempt = 0; $taskAttempt -lt 30; $taskAttempt++) {
    if ((Test-TaskService 'http://127.0.0.1:8000/api/v1/health') -and (Test-TaskService 'http://127.0.0.1:3000/login')) { $taskReady = $true; break }
    Start-Sleep -Seconds 1
}
if (-not $taskReady) { throw 'Startup did not complete. Inspect .local/api.stderr.log and .local/web.stderr.log.' }
Write-Output 'Ready: http://127.0.0.1:3000'
Write-Output 'Local demo accounts: .local/DEMO_ACCOUNTS.md'
