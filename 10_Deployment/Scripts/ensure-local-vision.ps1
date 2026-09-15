param([switch]$DownloadModel)

$ErrorActionPreference = 'Stop'
$taskProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$taskLocal = Join-Path $taskProjectRoot '.local'
$taskOllama = Get-Command ollama.exe -ErrorAction SilentlyContinue
if (-not $taskOllama) {
    if ($DownloadModel) { throw 'Install Ollama first, then run this script again.' }
    Write-Warning 'Local visual understanding unavailable: Ollama is not installed. Text extraction remains available.'
    return
}
$taskPreviousHost = $env:OLLAMA_HOST
$taskPreviousCloud = $env:OLLAMA_NO_CLOUD
try {
    $env:OLLAMA_HOST = '127.0.0.1:11434'
    $env:OLLAMA_NO_CLOUD = '1'
    $taskReady = $false
    try { $taskReady = (Invoke-WebRequest -UseBasicParsing -Uri 'http://127.0.0.1:11434/api/version' -TimeoutSec 2).StatusCode -eq 200 } catch { }
    if (-not $taskReady) {
        New-Item -ItemType Directory -Path $taskLocal -Force | Out-Null
        Start-Process -FilePath $taskOllama.Source -ArgumentList 'serve' -WindowStyle Hidden -RedirectStandardOutput (Join-Path $taskLocal 'ollama.stdout.log') -RedirectStandardError (Join-Path $taskLocal 'ollama.stderr.log') | Out-Null
        for ($taskAttempt = 0; $taskAttempt -lt 15; $taskAttempt++) {
            try {
                $taskReady = (Invoke-WebRequest -UseBasicParsing -Uri 'http://127.0.0.1:11434/api/version' -TimeoutSec 2).StatusCode -eq 200
                if ($taskReady) { break }
            } catch { }
            Start-Sleep -Seconds 1
        }
    }
    if (-not $taskReady) { throw 'Ollama did not start. Inspect .local/ollama.stderr.log.' }
    if ($DownloadModel) {
        & $taskOllama.Source pull 'qwen3-vl:8b-instruct'
        if ($LASTEXITCODE -ne 0) { throw 'Local vision model download failed.' }
    }
    $taskModel = Invoke-RestMethod -Method Post -Uri 'http://127.0.0.1:11434/api/show' -ContentType 'application/json' -Body '{"model":"qwen3-vl:8b-instruct"}' -TimeoutSec 10
    if ('vision' -notin $taskModel.capabilities) { throw 'The installed model does not support vision.' }
    Write-Output 'Local visual understanding ready: qwen3-vl:8b-instruct.'
} catch {
    if ($DownloadModel) { throw }
    Write-Warning 'Local visual understanding unavailable. Run ensure-local-vision.ps1 -DownloadModel during setup. Text extraction remains available.'
} finally {
    $env:OLLAMA_HOST = $taskPreviousHost
    $env:OLLAMA_NO_CLOUD = $taskPreviousCloud
}
