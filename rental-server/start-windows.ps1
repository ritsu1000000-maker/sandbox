param(
    [string]$AdminPassword = ""
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest
Set-Location $PSScriptRoot

function New-HexSecret([int]$ByteCount) {
    $bytes = New-Object byte[] $ByteCount
    $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    try {
        $rng.GetBytes($bytes)
    }
    finally {
        $rng.Dispose()
    }
    return ([System.BitConverter]::ToString($bytes) -replace "-", "").ToLowerInvariant()
}

Write-Host "[1/6] Docker Desktop を確認中..."
if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    throw "docker コマンドが見つかりません。Docker Desktop をインストールして起動してください。"
}

$dockerOs = (& docker info --format '{{.OSType}}' 2>$null)
if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($dockerOs)) {
    throw "Docker Desktop に接続できません。Docker Desktop を起動してから再実行してください。"
}
if ($dockerOs.Trim() -ne "linux") {
    throw "Docker Desktop を Linux containers モードに切り替えてください。"
}

Write-Host "[2/6] Python 仮想環境を確認中..."
$venvPython = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $venvPython)) {
    if (Get-Command py -ErrorAction SilentlyContinue) {
        & py -3 -m venv .venv
    }
    elseif (Get-Command python -ErrorAction SilentlyContinue) {
        & python -m venv .venv
    }
    else {
        throw "Python 3 が見つかりません。Python 3 をインストールしてください。"
    }
}

Write-Host "[3/6] Python パッケージを準備中..."
& $venvPython -m pip install --disable-pip-version-check -q -r requirements.txt
if ($LASTEXITCODE -ne 0) {
    throw "Python パッケージのインストールに失敗しました。"
}

$statePath = Join-Path $PSScriptRoot ".windows-state.json"
if (Test-Path $statePath) {
    $state = Get-Content $statePath -Raw | ConvertFrom-Json
}
else {
    $state = [pscustomobject]@{
        admin_password = (New-HexSecret 8)
        session_secret = (New-HexSecret 32)
        runner_token   = (New-HexSecret 32)
        runner_pid     = $null
        control_pid    = $null
    }
}

if (-not [string]::IsNullOrWhiteSpace($AdminPassword)) {
    $state.admin_password = $AdminPassword
}

foreach ($property in @("runner_pid", "control_pid")) {
    $oldPid = $state.$property
    if ($oldPid) {
        $oldProcess = Get-Process -Id $oldPid -ErrorAction SilentlyContinue
        if ($oldProcess) {
            Stop-Process -Id $oldPid -Force -ErrorAction SilentlyContinue
            Start-Sleep -Milliseconds 300
        }
    }
}

$state.runner_pid = $null
$state.control_pid = $null
$state | ConvertTo-Json | Set-Content $statePath -Encoding UTF8

$env:ADMIN_PASSWORD = [string]$state.admin_password
$env:SESSION_SECRET = [string]$state.session_secret
$env:RUNNER_TOKEN = [string]$state.runner_token
$env:RUNNER_URL = "http://127.0.0.1:9000"
$env:RUNNER_PORT = "9000"
$env:PORT = "8080"
$env:MAX_INSTANCES = "10"

$logsDir = Join-Path $PSScriptRoot "logs"
New-Item -ItemType Directory -Path $logsDir -Force | Out-Null
$runnerOut = Join-Path $logsDir "runner.out.log"
$runnerErr = Join-Path $logsDir "runner.err.log"
$controlOut = Join-Path $logsDir "control.out.log"
$controlErr = Join-Path $logsDir "control.err.log"
Set-Content $runnerOut "" -Encoding UTF8
Set-Content $runnerErr "" -Encoding UTF8
Set-Content $controlOut "" -Encoding UTF8
Set-Content $controlErr "" -Encoding UTF8

Write-Host "[4/6] Docker Runner を起動中..."
$runnerProcess = Start-Process \
    -FilePath $venvPython \
    -ArgumentList @("run_windows.py", "runner") \
    -WorkingDirectory $PSScriptRoot \
    -WindowStyle Hidden \
    -RedirectStandardOutput $runnerOut \
    -RedirectStandardError $runnerErr \
    -PassThru

$runnerReady = $false
for ($i = 0; $i -lt 30; $i++) {
    Start-Sleep -Milliseconds 500
    if ($runnerProcess.HasExited) { break }
    try {
        $health = Invoke-RestMethod -Uri "http://127.0.0.1:9000/health" -TimeoutSec 2
        if ($health.ok) {
            $runnerReady = $true
            break
        }
    }
    catch { }
}

if (-not $runnerReady) {
    Stop-Process -Id $runnerProcess.Id -Force -ErrorAction SilentlyContinue
    Write-Host "`n--- runner.err.log ---"
    Get-Content $runnerErr -ErrorAction SilentlyContinue
    throw "Runner の起動に失敗しました。"
}

Write-Host "[5/6] 管理画面を起動中..."
$controlProcess = Start-Process \
    -FilePath $venvPython \
    -ArgumentList @("run_windows.py", "control") \
    -WorkingDirectory $PSScriptRoot \
    -WindowStyle Hidden \
    -RedirectStandardOutput $controlOut \
    -RedirectStandardError $controlErr \
    -PassThru

$controlReady = $false
for ($i = 0; $i -lt 30; $i++) {
    Start-Sleep -Milliseconds 500
    if ($controlProcess.HasExited) { break }
    try {
        $health = Invoke-RestMethod -Uri "http://127.0.0.1:8080/health" -TimeoutSec 2
        if ($health.ok) {
            $controlReady = $true
            break
        }
    }
    catch { }
}

if (-not $controlReady) {
    Stop-Process -Id $controlProcess.Id -Force -ErrorAction SilentlyContinue
    Stop-Process -Id $runnerProcess.Id -Force -ErrorAction SilentlyContinue
    Write-Host "`n--- control.err.log ---"
    Get-Content $controlErr -ErrorAction SilentlyContinue
    throw "管理画面の起動に失敗しました。"
}

$state.runner_pid = $runnerProcess.Id
$state.control_pid = $controlProcess.Id
$state | ConvertTo-Json | Set-Content $statePath -Encoding UTF8

Write-Host "[6/6] 起動完了" -ForegroundColor Green
Write-Host ""
Write-Host "管理画面 : http://127.0.0.1:8080"
Write-Host "パスワード: $($state.admin_password)"
Write-Host ""
Write-Host "停止      : .\stop-windows.ps1"
Write-Host "ログ      : .\logs\"
