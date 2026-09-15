param([string]$PythonExecutable = '')
$ErrorActionPreference = 'Stop'
$taskProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$taskBackend = Join-Path $taskProjectRoot '04_Source_Code\backend'
$taskWeb = Join-Path $taskProjectRoot '04_Source_Code\web'
$taskPython = Join-Path $taskBackend '.venv\Scripts\python.exe'
$taskNpm = (Get-Command npm.cmd -ErrorAction Stop).Source
$taskNodeVersion = & node.exe --version
if ($taskNodeVersion -notmatch '^v24\.') { throw 'This local setup was validated with Node.js 24 LTS. Install Node.js 24 first.' }
if (-not (Test-Path -LiteralPath $taskPython)) {
    if (-not $PythonExecutable) {
        $PythonExecutable = & py.exe -3.13 -c 'import sys; print(sys.executable)'
        if ($LASTEXITCODE -ne 0) { throw 'Install Python 3.13, or pass -PythonExecutable with its executable path.' }
    }
    & $PythonExecutable -m venv (Join-Path $taskBackend '.venv')
    if ($LASTEXITCODE -ne 0) { throw 'Python virtual environment creation failed.' }
}
& $taskPython -m pip install -r (Join-Path $taskBackend 'requirements.lock.txt')
if ($LASTEXITCODE -ne 0) { throw 'Backend dependency installation failed.' }
& $taskPython (Join-Path $PSScriptRoot 'install_postgres.py')
if ($LASTEXITCODE -ne 0) { throw 'PostgreSQL binary installation failed.' }
& $taskPython (Join-Path $PSScriptRoot 'bootstrap_local.py')
if ($LASTEXITCODE -ne 0) { throw 'Database initialization failed. Inspect .local/bootstrap.log.' }
Push-Location -LiteralPath $taskBackend
try {
    & $taskPython -m alembic upgrade head
    if ($LASTEXITCODE -ne 0) { throw 'Database migration failed.' }
    & $taskPython -m app.seed
    if ($LASTEXITCODE -ne 0) { throw 'Demo account setup failed.' }
} finally { Pop-Location }
Push-Location -LiteralPath $taskWeb
try {
    & $taskNpm ci
    if ($LASTEXITCODE -ne 0) { throw 'Web dependency installation failed. Stop the project before setup.' }
    & $taskNpm exec -- playwright install chromium --only-shell
    if ($LASTEXITCODE -ne 0) { throw 'Browser test runtime installation failed.' }
} finally { Pop-Location }
& $taskPython (Join-Path $PSScriptRoot 'create-demo-document.py')
if ($LASTEXITCODE -ne 0) { throw 'Demo document creation failed.' }
Write-Output 'Setup complete. Run Start_Project.cmd from the project folder.'
