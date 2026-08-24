# Rental Server MVP

利用者がプランを選んで自分専用サーバーを作成・起動・停止・再起動・削除できるレンタルサーバーサイトです。

**管理者ログインや管理パスワードはありません。**

サーバー作成時にそのサーバー専用の管理キーを自動発行し、ブラウザへ保存します。Start / Stop / Restart / Logs / Delete はその管理キーを持つ利用者だけが実行できます。

## プラン

| 容量 | 月額 | RAM | CPU |
| ---: | ---: | ---: | ---: |
| 500MB | 無料 | 128MB | 0.1 |
| 1GB | 500円 | 256MB | 0.25 |
| 10GB | 1,500円 | 512MB | 0.5 |
| 50GB | 2,000円 | 1GB | 1.0 |
| 100GB | 4,000円 | 2GB | 2.0 |

Windows Docker Desktopでは容量値は契約プラン情報として管理しています。CPU/RAM制限はDockerへ実際に適用します。厳密な永続ディスククォータは別途ストレージ機構が必要です。

Render APIモードでは、表示している容量・RAM・CPUはレンタルサイト上のプラン情報です。Render側の実際のインスタンスタイプや永続ディスク容量とは別に管理されます。

## 利用者向け画面

- ログインなし
- プラン選択
- サーバー名入力
- Python Web / Node Web / Nginx選択
- サーバー作成
- Start / Stop / Restart
- Logs
- Delete
- 管理キーによるサーバー再登録

作成したサーバーの管理キーはブラウザのLocal Storageへ保存されます。

# Render公開

RenderではDocker Runnerへ接続せず、Render REST APIを使って利用者用Web Serviceを作成・管理します。

## Render Web Service設定

GitHubリポジトリ:

```text
https://github.com/ritsu1000000-maker/sandbox
```

設定:

```text
Branch: rental-server-mvp
Root Directory: rental-server
Language: Python 3
Build Command: pip install -r requirements.txt
Start Command: gunicorn app:app --bind 0.0.0.0:$PORT
Health Check Path: /health
```

## Environment Variables

RenderのWeb Serviceに次を追加します。

```text
BACKEND_PROVIDER=render
RENDER_API_KEY=<Render API Key>
RENDER_OWNER_ID=<Render Workspace ID>
INSTANCE_KEY_SECRET=<長いランダム文字列>
```

任意設定:

```text
RENDER_TENANT_REPO=https://github.com/ritsu1000000-maker/sandbox
RENDER_TENANT_BRANCH=rental-server-mvp
RENDER_TENANT_REGION=singapore
RENDER_SERVICE_PREFIX=rental
```

`RENDER_API_KEY` はRender DashboardのAccount Settingsで作成し、GitHubへコミットせずRenderのEnvironment Variableだけに保存してください。

`RENDER_OWNER_ID` はRender WorkspaceのIDです。

`INSTANCE_KEY_SECRET` は利用者用サーバーの管理キー生成に使う内部秘密値です。公開画面には表示されません。

## 有料プランについて

Render APIモードでは、初期状態で500MB無料プランだけ自動作成できます。

有料プランを匿名ユーザーが自由に作成できるようにすると、Renderアカウント側へ実際の利用料金が発生する可能性があるため、決済確認を実装するまでは自動作成を無効にしています。

`ALLOW_PAID_RENDER_PLANS=true` を設定するとコード上は有料Renderプランへのマッピングが有効になりますが、公開運用では先に決済確認・利用制限・不正利用対策を実装してください。

## Render APIモードの構成

```text
利用者ブラウザ
  |
  v
Rental Server Web (Render)
  |
  | Render REST API
  v
Render Workspace
  |
  +-- rental-example-free-py
  +-- rental-example2-free-node
  +-- rental-example3-free-nginx
```

Start / Stop / Restart / Delete はRender APIのResume / Suspend / Restart / Deleteへ変換されます。

# Windows 10 / 11

## 必要なもの

- Windows 10 / 11
- Docker Desktop
- Docker DesktopのLinux containersモード
- Python 3
- PowerShell

## 起動

```powershell
cd rental-server
.\start-windows.ps1
```

起動後:

```text
http://127.0.0.1:8080
```

ログインや管理者パスワードは不要です。

## 停止

```powershell
.\stop-windows.ps1
```

# Linux / Docker Compose

```bash
cd rental-server
RUNNER_TOKEN='long-random-runner-token' \
docker compose up -d --build
```

公開する場合は `RUNNER_TOKEN` を必ず十分長いランダム値へ変更してください。

# Docker Runner構成

```text
利用者ブラウザ
  |
  v
Rental Server Web :8080
  |
  | RUNNER_TOKEN
  v
Runner :9000
  |
  v
Docker Engine
  |
  +-- rental-user-server-1
  +-- rental-user-server-2
```

Runnerは外部へ直接公開しないでください。

# 今後

- 決済完了後の有料プラン有効化
- ユーザーアカウント
- 永続ディスク容量クォータ
- 独自ドメイン
- HTTPS
- 利用期限
- CPU/RAMグラフ
- Render APIログ取得
