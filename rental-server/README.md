# Rental Server

Python / Flaskを中心にしたレンタルサーバー管理サイトです。利用者はプランと実行環境を選び、自分専用のサーバーを作成・起動・停止・再起動・削除できます。

## 構成

```text
Browser
  |
  v
Flask Web / API
  |
  v
RentalManager
  |
  +-- RenderProvider ----> Render REST API
  |
  +-- RunnerProvider ----> Docker Runner ----> isolated containers
```

```text
rental-server/
├─ app.py
├─ server.py                 # 設定/起動CLI
├─ server.env.example        # 推奨設定テンプレート
├─ .env.example              # dotenv互換テンプレート
├─ gunicorn.conf.py          # 本番Webサーバー設定
├─ Dockerfile
├─ docker-compose.yml
├─ start-windows.ps1
├─ stop-windows.ps1
├─ runner.py
├─ rental_core/
│  ├─ config.py
│  ├─ env_loader.py
│  ├─ errors.py
│  ├─ manager.py
│  ├─ providers.py
│  ├─ rate_limit.py
│  └─ security.py
├─ templates/
└─ static/
```

## 設定ファイルの優先順位

設定値は次の順で優先されます。

1. Render / OS / PowerShellなどの実際のプロセス環境変数
2. `RENTAL_ENV_FILE` で明示したファイル
3. `server.env`
4. `.env`

ローカルでは `server.env` を推奨します。Render公開時はファイルを置かず、Render DashboardのEnvironment Variablesを使ってください。

`server.env` と `.env` は `.gitignore` 済みです。実APIキーや秘密値をGitHubへコミットしないでください。

# 初回セットアップ

## Windows: 一番簡単な方法

Docker Desktopを起動し、Linux containersモードにしたあと:

```powershell
cd rental-server
.\start-windows.ps1
```

初回実行時に自動で:

- `.venv` 作成
- Python依存パッケージ導入
- `server.env` 作成
- `RUNNER_TOKEN` の安全なランダム生成
- `INSTANCE_KEY_SECRET` の安全なランダム生成
- Docker Runner起動
- Webサービス起動
- ヘルスチェック
- ログディレクトリ作成

まで行います。

起動後:

```text
http://127.0.0.1:8080
```

停止:

```powershell
.\stop-windows.ps1
```

ログ:

```text
logs/runner.out.log
logs/runner.err.log
logs/control.out.log
logs/control.err.log
```

## 手動セットアップ

```bash
python -m venv .venv
```

Windows:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe server.py init-env
.\.venv\Scripts\python.exe server.py check
```

Linux / macOS:

```bash
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python server.py init-env
.venv/bin/python server.py check
```

設定に問題がなければ、RunnerとWebをそれぞれ起動できます。

```bash
python server.py runner
python server.py web
```

# server.env

テンプレートは `server.env.example` です。

```text
BACKEND_PROVIDER=runner
APP_HOST=0.0.0.0
PORT=8080
CREATE_LIMIT_PER_HOUR=10
LOG_LEVEL=INFO
INSTANCE_KEY_SECRET=<自動生成された秘密値>

RUNNER_HOST=127.0.0.1
RUNNER_PORT=9000
RUNNER_URL=http://127.0.0.1:9000
RUNNER_TOKEN=<自動生成された秘密値>
MAX_INSTANCES=10

RENDER_API_KEY=
RENDER_OWNER_ID=
RENDER_TENANT_REPO=https://github.com/ritsu1000000-maker/sandbox
RENDER_TENANT_BRANCH=rental-server-mvp
RENDER_TENANT_REGION=singapore
RENDER_SERVICE_PREFIX=rental
ALLOW_PAID_RENDER_PLANS=false
REQUEST_TIMEOUT_SECONDS=30
```

### 主な設定

| 変数 | 用途 |
| --- | --- |
| `BACKEND_PROVIDER` | `runner` または `render` |
| `APP_HOST` | Webの待受アドレス |
| `PORT` | Webポート |
| `INSTANCE_KEY_SECRET` | サーバー管理キー用の秘密値 |
| `CREATE_LIMIT_PER_HOUR` | IPごとの作成回数上限 |
| `RUNNER_HOST` | Docker Runner待受アドレス |
| `RUNNER_PORT` | Docker Runnerポート |
| `RUNNER_URL` | WebからRunnerへ接続する内部URL |
| `RUNNER_TOKEN` | Web→Runner間の認証トークン |
| `MAX_INSTANCES` | ローカルDockerで作成できる最大数 |
| `RENDER_API_KEY` | Render REST APIキー。秘密情報 |
| `RENDER_OWNER_ID` | Render Workspace ID |
| `RENDER_TENANT_REGION` | 利用者用Render Serviceのリージョン |
| `ALLOW_PAID_RENDER_PLANS` | 有料Renderプラン自動作成の許可 |
| `REQUEST_TIMEOUT_SECONDS` | Provider API通信タイムアウト |
| `LOG_LEVEL` | アプリ/Gunicornログレベル |

# server.py CLI

```text
python server.py init-env
python server.py init-env --force
python server.py check
python server.py web
python server.py runner
```

`init-env` は `server.env.example` から `server.env` を作り、秘密値を自動生成します。

`check` はProvider、ポート、秘密値、Render設定などを確認します。APIキーの値そのものは表示しません。

# Docker Compose

まず設定を作ります。

```bash
python server.py init-env
```

その後:

```bash
docker compose up -d --build
```

`docker-compose.yml` は `server.env` をcontrol / runnerへ読み込みます。RunnerだけがDocker socketを扱い、control側にはDocker socketを渡しません。

停止:

```bash
docker compose down
```

# Render公開

RenderではDocker Runnerを起動せず、Render REST APIを使います。

## Web Service

```text
Repository: https://github.com/ritsu1000000-maker/sandbox
Branch: rental-server-mvp
Root Directory: rental-server
Runtime: Python 3
Build Command: pip install -r requirements.txt
Start Command: gunicorn -c gunicorn.conf.py app:app
Health Check Path: /health
```

現在の古いStart Command `gunicorn app:app --bind 0.0.0.0:$PORT` でも起動できますが、`gunicorn.conf.py` を使う方を推奨します。

## Render Environment Variables

最低限:

```text
BACKEND_PROVIDER=render
RENDER_API_KEY=<Render API Key>
RENDER_OWNER_ID=<Render Workspace ID>
INSTANCE_KEY_SECRET=<長いランダム文字列>
ALLOW_PAID_RENDER_PLANS=false
```

推奨:

```text
RENDER_TENANT_REPO=https://github.com/ritsu1000000-maker/sandbox
RENDER_TENANT_BRANCH=rental-server-mvp
RENDER_TENANT_REGION=singapore
RENDER_SERVICE_PREFIX=rental
CREATE_LIMIT_PER_HOUR=10
REQUEST_TIMEOUT_SECONDS=30
LOG_LEVEL=INFO
WEB_CONCURRENCY=2
GUNICORN_THREADS=4
GUNICORN_TIMEOUT=60
```

`RENDER_API_KEY` と `INSTANCE_KEY_SECRET` は公開禁止です。`RENDER_OWNER_ID` は識別子でありAPIキーではありません。

Render上では `BACKEND_PROVIDER` が未設定でもRender環境を自動検出しますが、明示的に `render` を設定することを推奨します。

# Webページ

| URL | 内容 |
| --- | --- |
| `/` | トップページ |
| `/plans` | 料金・性能比較 |
| `/create` | サーバー作成 |
| `/servers` | マイサーバー一覧 |
| `/servers/<name>` | 1台ごとの管理画面 |
| `/import` | 管理キーで既存サーバーを追加 |
| `/health` | 稼働確認 |
| `/api/system` | バックエンド状態・機能情報 |

# プラン

| 容量 | 月額 | RAM | CPU |
| ---: | ---: | ---: | ---: |
| 500MB | 無料 | 128MB | 0.1 |
| 1GB | 500円 | 256MB | 0.25 |
| 10GB | 1,500円 | 512MB | 0.5 |
| 50GB | 2,000円 | 1GB | 1.0 |
| 100GB | 4,000円 | 2GB | 2.0 |

表示容量・RAM・CPUはレンタルサイト側のプラン情報です。Render APIモードではRenderの実際のインスタンスタイプや永続ディスクとは別管理です。Docker RunnerモードではCPU/RAM制限をDockerへ適用します。

# セキュリティ方針

- 利用者へホストOSの `cmd.exe` を直接公開しない
- control側へDocker socketを渡さない
- Runner APIは `RUNNER_TOKEN` で保護
- サーバー操作はサーバー単位の管理キーで保護
- Render APIキーはバックエンドだけで使用
- `server.env` / `.env` はGit管理しない
- Docker利用者コンテナはread-only、capabilities drop、no-new-privileges、PID/RAM/CPU制限を使用
- 有料Renderサービスの自動作成は初期状態で無効

# まだ必要な本番機能

現在でも小規模な管理サイトとして動きますが、商用レンタルサーバーとして運営するにはさらに以下が必要です。

- PostgreSQLによるユーザー・契約・監査ログ
- メール認証/アカウント復旧
- 決済確認後だけ有料プランを有効化
- 実際の永続ディスク容量クォータ
- Render実ログ取得
- CPU/RAM/リクエスト数の監視グラフ
- Redis等を使った共有レート制限
- ファイルアップロード時の容量/拡張子/Zip Slip対策
- 利用期限・自動停止
- バックアップと復旧
