# Rental Server MVP

Dockerで隔離した小型Webインスタンスを、ブラウザから作成・起動・停止・再起動・削除できるレンタルサーバー管理パネルです。

## 入っている機能

- 管理者ログイン
- インスタンス作成 / Start / Stop / Restart / Delete
- ログ表示（直近200行）
- Python / Node.js / Nginx テンプレート
- Small: 256MB RAM / 0.25 CPU
- Medium: 512MB RAM / 0.5 CPU
- 最大インスタンス数の制限
- DockerコンテナごとのCPU・RAM・PID制限
- privileged無効、capabilities全削除、no-new-privileges
- ホストディレクトリをユーザー用コンテナへマウントしない設計

## 必要なもの

- Linuxサーバー
- Docker Engine
- Docker Compose v2

Windows Docker Desktopでも開発確認はできますが、公開運用はLinuxサーバー推奨です。

## 起動

```bash
cd rental-server
ADMIN_PASSWORD='your-admin-password' \
SESSION_SECRET='long-random-session-secret' \
RUNNER_TOKEN='long-random-runner-token' \
docker compose up -d --build
```

起動後:

- 管理画面: `http://SERVER_IP:8080`
- Runnerは外部ポートへ公開されません

## 停止

```bash
docker compose down
```

## ログ

```bash
docker compose logs -f control runner
```

## 構成

```text
Browser
  |
  v
control :8080
  |
  | internal HTTP + RUNNER_TOKEN
  v
runner :9000 (外部非公開)
  |
  v
Docker Engine
  |
  +-- rental-example1
  +-- rental-example2
```

`runner` だけが Docker socket を利用します。`runner:9000` はインターネットへ直接公開しないでください。

## テンプレート

### python-web

`python:3.12-alpine` で `python -m http.server` を起動します。

### node-web

`node:22-alpine` で固定のHTTPサーバーを起動します。

### nginx

`nginx:alpine` の標準ページを起動します。

このMVPでは、管理画面から任意のシェルコマンドやホスト側コマンドを直接入力する機能は付けていません。テンプレートを増やす場合は `runner.py` の `TEMPLATES` に許可するイメージと固定コマンドを追加します。

## 公開運用前に変更するもの

必ず `ADMIN_PASSWORD`、`SESSION_SECRET`、`RUNNER_TOKEN` をデフォルト値から変更してください。また8080番を直接公開するより、Caddy / Nginx / Cloudflare Tunnel等のHTTPSリバースプロキシ配下に置く構成を推奨します。

## 今後追加しやすい機能

- ユーザーアカウント / 契約プラン
- ディスク容量クォータ
- DBインスタンス
- 独自ドメイン
- HTTPS自動発行
- 請求・利用期限
- CPU / RAM使用率グラフ
- WebSocketリアルタイムログ
- 複数ホストへのRunner分散
