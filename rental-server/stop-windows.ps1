$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest
Set-Location $PSScriptRoot

$statePath = Join-Path $PSScriptRoot ".windows-state.json"
if (-not (Test-Path $statePath)) {
    Write-Host "起動状態ファイルがありません。すでに停止している可能性があります。"
    exit 0
}

$state = Get-Content $statePath -Raw | ConvertFrom-Json
$stopped = 0

foreach ($property in @("control_pid", "runner_pid")) {
    $processId = $state.$property
    if ($processId) {
        $process = Get-Process -Id $processId -ErrorAction SilentlyContinue
        if ($process) {
            Stop-Process -Id $processId -Force -ErrorAction SilentlyContinue
            $stopped++
        }
        $state.$property = $null
    }
}

$state | ConvertTo-Json | Set-Content $statePath -Encoding UTF8
Write-Host "管理パネルを停止しました。($stopped プロセス)" -ForegroundColor Green
Write-Host "作成済みのレンタルサーバー用Dockerコンテナはそのまま稼働します。"
