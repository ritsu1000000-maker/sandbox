$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest
Set-Location $PSScriptRoot

function New-HexSecret([int]$ByteCount) {
    $bytes = New-Object byte[] $ByteCount
    $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    try { $rng.GetBytes($bytes) } finally { $rng.Dispose() }
    return ([System.BitConverter]::ToString($bytes) -replace "-", "").ToLowerInvariant()
}

function Import-DotEnv([string]$Path) {
    if (-not (Test-Path $Path)) { return }
    foreach ($line in Get-Content $Path) {
        $trimmed = $line.Trim()
        if (-not $trimmed -or $trimmed.StartsWith("#")) { continue }
        $parts = $trimmed -split "=", 2
        if ($parts.Count -ne 2) { continue }
        $name = $parts[0].Trim()
        $value = $parts[1].Trim()
        if (($value.StartsWith('"') -and $value.EndsWith('"')) -or ($value.StartsWith("'") -and $value.EndsWith("'"))) {
            $value = $value.Substring(1, $value.Length - 2)
        }
        if ($name) { [Environment]::SetEnvironmentVariable($name, $value, "Process") }
    }
}

function Set-DotEnvValue([string]$Path, [string]$Name, [string]$Value) {
    $lines = @()
    if (Test-Path $Path) { $lines = @(Get-Content $Path) }
    $found = $false
    $updated = foreach ($line in $lines) {
        if ($line -match "^\s*$([regex]::Escape($Name))=") {
            $found = $true
            "$Name=$Value"
        } else {
            $line
        }
    }
    if (-not $found) { $updated += "$Name=$Value" }
    $updated | Set-Content $Path -Encoding UTF8
    [Environment]::SetEnvironmentVariable($Name, $Value, "Process")
}

Write-Host "[1/7] Docker Desktop を確認中..."
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

Write-Host "[2/7] Python 仮想環境を確認中..."
$venvPython = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $venvPython)) {
    if (Get-Command py -ErrorAction SilentlyContinue) { & py -3 -m venv .venv }
    elseif (Get-Command python -ErrorAction SilentlyContinue) { & python -m venv .venv }
    else { throw "Python 3 が見つかりません。Python 3 をインストールしてください。" }
}

Write-Host "[3/7] Python パッケージを準備中..."
& $venvPython -m pip install --disable-pip-version-check -q -r requirements.txt
if ($LASTEXITCODE -ne 0) { throw "Python パッケージのインストールに失敗しました。" }

Write-Host "[4/7] server.env を準備中..."
$serverEnv = Join-Path $PSScriptRoot "server.env"
if (-not (Test-Path $serverEnv)) {
    & $venvPython server.py init-env
    if ($LASTEXITCODE -ne 0) { throw "server.env の生成に失敗しました。" }
}
Import-DotEnv $serverEnv

# This script is specifically the local Docker-runner launcher.
$env:BACKEND_PROVIDER = "runner"
Set-DotEnvValue $serverEnv "BACKEND_PROVIDER" "runner"

if ([string]::IsNullOrWhiteSpace($env:RUNNER_TOKEN) -or $env:RUNNER_TOKEN -eq "CHANGE_ME_GENERATED") {
    Set-DotEnvValue $serverEnv "RUNNER_TOKEN" (New-HexSecret 32)
}
if ([string]::IsNullOrWhiteSpace($env:INSTANCE_KEY_SECRET) -or $env:INSTANCE_KEY_SECRET -eq "CHANGE_ME_GENERATED") {
    Set-DotEnvValue $serverEnv "INSTANCE_KEY_SECRET" (New-HexSecret 32)
}

# Reload after any repairs.
Import-DotEnv $serverEnv
$webPort = if ($env:PORT) { [int]$env:PORT } else { 8080 }
$runnerPort = if ($env:RUNNER_PORT) { [int]$env:RUNNER_PORT } else { 9000 }
if (-not $env:RUNNER_HOST) { $env:RUNNER_HOST = "127.0.0.1" }
if (-not $env:RUNNER_URL) { $env:RUNNER_URL = "http://$($env:RUNNER_HOST):$runnerPort" }

Write-Host "[5/7] 既存プロセスとポートを確認中..."
$statePath = Join-Path $PSScriptRoot ".windows-state.json"
if (Test-Path $statePath) {
    $state = Get-Content $statePath -Raw | ConvertFrom-Json
} else {
    $state = [pscustomobject]@{ runner_pid=$null; control_pid=$null }
}
foreach ($property in @("runner_pid", "control_pid")) {
    if (-not ($state.PSObject.Properties.Name -contains $property)) {
        $state | Add-Member -NotePropertyName $property -NotePropertyValue $null
    }
    $oldPid = $state.$property
    if ($oldPid) {
        $oldProcess = Get-Process -Id $oldPid -ErrorAction SilentlyContinue
        if ($oldProcess) {
            Stop-Process -Id $oldPid -Force -ErrorAction SilentlyContinue
            Start-Sleep -Milliseconds 300
        }
    }
}
foreach ($port in @($webPort, $runnerPort)) {
    $listener = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($listener) { throw "ポート $port は別のプロセス (PID $($listener.OwningProcess)) が使用中です。" }
}
$state.runner_pid = $null
$state.control_pid = $null
$state | ConvertTo-Json | Set-Content $statePath -Encoding UTF8

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

Write-Host "[6/7] Runner とWebを起動中..."
$runnerStart = @{
    FilePath=$venvPython; ArgumentList=@("run_windows.py", "runner"); WorkingDirectory=$PSScriptRoot;
    WindowStyle="Hidden"; RedirectStandardOutput=$runnerOut; RedirectStandardError=$runnerErr; PassThru=$true
}
$runnerProcess = Start-Process @runnerStart

$runnerReady = $false
for ($i=0; $i -lt 40; $i++) {
    Start-Sleep -Milliseconds 500
    if ($runnerProcess.HasExited) { break }
    try {
        $health = Invoke-RestMethod -Uri "http://127.0.0.1:$runnerPort/health" -TimeoutSec 2
        if ($health.ok) { $runnerReady=$true; break }
    } catch {}
}
if (-not $runnerReady) {
    Stop-Process -Id $runnerProcess.Id -Force -ErrorAction SilentlyContinue
    Get-Content $runnerErr -ErrorAction SilentlyContinue
    throw "Runner の起動に失敗しました。"
}

$controlStart = @{
    FilePath=$venvPython; ArgumentList=@("run_windows.py", "control"); WorkingDirectory=$PSScriptRoot;
    WindowStyle="Hidden"; RedirectStandardOutput=$controlOut; RedirectStandardError=$controlErr; PassThru=$true
}
$controlProcess = Start-Process @controlStart

$controlReady = $false
for ($i=0; $i -lt 40; $i++) {
    Start-Sleep -Milliseconds 500
    if ($controlProcess.HasExited) { break }
    try {
        $health = Invoke-RestMethod -Uri "http://127.0.0.1:$webPort/health" -TimeoutSec 2
        if ($health.ok) { $controlReady=$true; break }
    } catch {}
}
if (-not $controlReady) {
    Stop-Process -Id $controlProcess.Id -Force -ErrorAction SilentlyContinue
    Stop-Process -Id $runnerProcess.Id -Force -ErrorAction SilentlyContinue
    Get-Content $controlErr -ErrorAction SilentlyContinue
    throw "サイトの起動に失敗しました。"
}

$state.runner_pid = $runnerProcess.Id
$state.control_pid = $controlProcess.Id
$state | ConvertTo-Json | Set-Content $statePath -Encoding UTF8

Write-Host "[7/7] 起動完了" -ForegroundColor Green
Write-Host ""
Write-Host "Rental Server : http://127.0.0.1:$webPort"
Write-Host "Runner        : http://127.0.0.1:$runnerPort"
Write-Host "設定          : .\server.env"
Write-Host "設定確認      : .\.venv\Scripts\python.exe server.py check"
Write-Host "停止          : .\stop-windows.ps1"
Write-Host "ログ          : .\logs\"
