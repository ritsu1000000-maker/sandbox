# Rental Server MVP

Dockerで隔離した小型Webインスタンスを、ブラウザから作成・起動・停止・再起動・削除できるレンタルサーバー管理パネルです。

Windows 10/11では **Docker Desktop + Python + PowerShell** で動作する構成を用意しています。Linuxでは従来どおりDocker Composeで起動できます。

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

# Windows 10 / 11

## 必要なもの

- Windows 10 または Windows 11
- Docker Desktop
- Docker Desktopの **Linux containers** モード
- Python 3
- PowerShell

Docker Desktopは起動した状態にしてください。

## 起動

PowerShellで `rental-server` フォルダへ移動して、次を実行します。

```powershell
.\start-windows.ps1
```

初回起動時は自動的に次を行います。

1. Docker Desktopの起動状態を確認
2. Linux containersモードを確認
3. `.venv` を作成
4. 必要なPythonパッケージをインストール
5. 管理者パスワード・内部トークンを生成
6. Runnerを `127.0.0.1:9000` で起動
7. 管理画面を `0.0.0.0:8080` で起動

正常に起動するとPowerShellに次のように表示されます。

```text
管理画面 : http://127.0.0.1:8080
パスワード: ********
```

ブラウザで `http://127.0.0.1:8080` を開いてログインしてください。

### 管理者パスワードを自分で指定する

```powershell
.\start-windows.ps1 -AdminPassword "好きな強いパスワード"
```

指定しない場合はランダムなパスワードを自動生成します。

## 停止

```powershell
.\stop-windows.ps1
```

管理パネルとRunnerのみ停止します。作成済みのレンタルサーバー用Dockerコンテナは停止せず、そのまま稼働します。

## Windows版ログ

```text
logs\control.out.log
logs\control.err.log
logs\runner.out.log
logs\runner.err.log
```

`.windows-state.json` にはWindows版の内部状態と自動生成した秘密情報が保存されます。このファイル、`.venv`、`logs` は `.gitignore` 対象です。

## Windows版の構成

```text
Browser
  |
  v
Windows control :8080
  |
  | localhost + RUNNER_TOKEN
  v
Windows runner :9000
  |
  | Docker SDK / Docker Desktop
  v
Docker Engine (Linux containers)
  |
  +-- rental-example1
  +-- rental-example2
```

Windows版ではRunner自体をDockerコンテナ内に入れず、Windows上のPythonプロセスとして起動します。これによりWindows上でLinux用 `/var/run/docker.sock` を直接マウントする必要がありません。

Runnerは `127.0.0.1:9000` のみにバインドされ、LANやインターネットから直接アクセスできない構成です。

# Linux / Docker Compose

## 必要なもの

- Linuxサーバー
- Docker Engine
- Docker Compose v2

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

# テンプレート

## python-web

`python:3.12-alpine` で `python -m http.server` を起動します。

## node-web

`node:22-alpine` で固定のHTTPサーバーを起動します。

## nginx

`nginxinc/nginx-unprivileged:alpine` の標準ページを8080番ポートで起動します。

このMVPでは、管理画面から任意のホスト側コマンドを直接入力する機能は付けていません。テンプレートを増やす場合は `runner.py` の `TEMPLATES` に許可するイメージと固定コマンドを追加します。

# 公開運用について

WindowsでもLAN内運用や開発はできます。インターネットへ公開する場合は、Windows Firewall、HTTPSリバースプロキシ、アクセス制御を設定してください。

24時間の公開サービスとして多数の利用者へ提供する場合は、Windows PCよりLinux VPS / 専用サーバー上でDocker Compose版を動かす構成を推奨します。

# 今後追加しやすい機能

- ユーザーアカウント / 契約プラン
- ファイルアップロード
- ディスク容量クォータ
- DBインスタンス
- 独自ドメイン
- HTTPS自動発行
- 請求・利用期限
- CPU / RAM使用率グラフ
- WebSocketリアルタイムログ
- 複数ホストへのRunner分散
