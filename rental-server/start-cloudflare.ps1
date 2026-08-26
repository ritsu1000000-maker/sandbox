$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot

if (-not (Test-Path 'server.env')) {
    Write-Host 'server.env がありません。生成します。' -ForegroundColor Yellow
    python server.py init-env
}

$envText = Get-Content 'server.env' -Raw
$match = [regex]::Match($envText, '(?m)^CLOUDFLARE_TUNNEL_TOKEN=(.+)$')
if (-not $match.Success -or [string]::IsNullOrWhiteSpace($match.Groups[1].Value)) {
    Write-Host ''
    Write-Host 'CLOUDFLARE_TUNNEL_TOKEN が未設定です。' -ForegroundColor Red
    Write-Host 'Cloudflare Dashboard > Networking > Tunnels でTunnelを作成し、トークンを server.env に設定してください。'
    Write-Host '例: CLOUDFLARE_TUNNEL_TOKEN=eyJh...'
    exit 1
}

Write-Host 'Hosting Service + Docker Runner + Cloudflare Tunnel を起動します...' -ForegroundColor Cyan
docker compose --profile cloudflare up -d --build

Write-Host ''
Write-Host '起動状態:' -ForegroundColor Cyan
docker compose --profile cloudflare ps

Write-Host ''
Write-Host 'ローカル確認: http://127.0.0.1:8080/health'
Write-Host 'Cloudflareの公開URLはTunnelに設定したPublic Hostnameです。' -ForegroundColor Green
