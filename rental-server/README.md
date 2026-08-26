# Hosting Service

Python / Node.js / Nginx を対象にした、アカウント型のアプリケーションホスティングサービスです。

利用者はアカウントを作成し、プランと実行環境を選択して、自分専用のサービスを発行・編集・Deploy・管理できます。

## 主な機能

- アカウント登録 / ログイン
- ユーザーごとのサービス所有権管理
- 500MB〜100GBのホスティングプラン
- Python Web / Node.js Web / Nginx
- Render Provider / Docker Runner Provider
- Start / Stop / Restart
- 公開URL
- ブラウザ内コードエディタ
- ZIPソースコードImport
- 隔離Project Terminal
- Build Command
- Start Command
- Root Directory
- Environment Variables
- Deploy進捗表示
- Buildログ / アプリ実行ログ
- 24時間モード（Always On）
- アプリ異常終了時のSupervisor自動再起動
- Docker `restart: unless-stopped`
- サービスごとの永続Docker Volume
- プラン・月額・更新予定の管理
- 無料プランの即時発行
- 有料プランの支払い確認待ち状態
- Render容量不足時の共有ホスティングfallback
- SQLite / PostgreSQL / Redis対応
- CSRF / Session / Security Headers

## Build / Deploy

Docker Runnerで発行した Python / Node.js サービスでは、コードエディタの **BUILD & DEPLOY** から実際の実行設定を保存できます。

### Python の初期値

```text
Build Command: pip install -r requirements.txt
Start Command: python -m gunicorn app:app --bind 0.0.0.0:$PORT
Root Directory: .
24時間モード: ON
```

Python依存パッケージはサービス専用Volume内の `.python` に保存されます。

### Node.js の初期値

```text
Build Command: npm install
Start Command: npm start
Root Directory: .
24時間モード: ON
```

`node_modules` もサービス専用Volume内に保持されます。

### Environment Variables

管理画面では以下のように設定します。

```text
DISCORD_TOKEN=example
API_URL=https://example.com
```

`PORT` / `HOST` / `HOME` / `PIP_TARGET` / `PYTHONPATH` / `npm_config_cache` はシステム側で設定するため予約済みです。

Environment Variablesは公開ProjectFileStoreとは別のPrivate Service Config Storeに保存し、公開ファイルURLから参照されない構成です。

## 24時間モード

Runnerサービスでは2段階で復旧します。

1. Docker Container: `restart_policy=unless-stopped`
2. Application Process: Runtime Supervisor

Start Commandのプロセスが終了すると、24時間モードがONの場合はSupervisorが再起動します。

ユーザーがStopを実行した場合はDocker Container自体が停止します。

## 隔離Runner

利用者の実行コードはcontrolサーバーやホストOSのシェルで直接実行しません。

Runnerが管理するサービスごとのDocker Container内で実行します。

主な制限:

- read-only root filesystem
- capability drop
- `no-new-privileges`
- PID limit
- RAM / CPU plan limit
- サービス専用Docker Volume
- Project Terminal command timeout
- Project sync size limit
- per-instance management key

## Webページ

| URL | 内容 |
| --- | --- |
| `/` | ホスティングサービスのトップ |
| `/plans` | Hosting Plans |
| `/signup` | アカウント作成 |
| `/login` | ログイン |
| `/dashboard` | ホスティングサービス一覧 |
| `/create` | 新しいサービスを作成 |
| `/servers/<service_id>` | サービス管理 |
| `/servers/<service_id>/editor` | Code Editor / Build & Deploy / Terminal |
| `/billing` | プラン・請求 |
| `/health` | 稼働確認 |
| `/api/system` | システム情報 |

## Runtime API

ログイン中のサービス所有者向けAPIです。

```text
GET  /api/contracts/<id>/settings
PUT  /api/contracts/<id>/settings
POST /api/contracts/<id>/deploy
GET  /api/contracts/<id>/runtime
GET  /api/contracts/<id>/runtime-logs
```

変更系APIにはCSRF Tokenが必要です。

## プラン

| Storage | 月額 | RAM | CPU |
| ---: | ---: | ---: | ---: |
| 500MB | ¥0 | 128MB | 0.1 |
| 1GB | ¥500 | 256MB | 0.25 |
| 10GB | ¥1,500 | 512MB | 0.5 |
| 50GB | ¥2,000 | 1GB | 1.0 |
| 100GB | ¥4,000 | 2GB | 2.0 |

表示しているStorage / RAM / CPUはホスティングサービス側のプラン値です。Provider側で実際に適用できる上限とは分けて管理します。

## ローカル起動

### Windows

Docker DesktopをLinux containersモードで起動してから:

```powershell
cd rental-server
.\start-windows.ps1
```

初回は自動で:

- `.venv` 作成
- Python依存パッケージ導入
- `server.env` 作成
- `RUNNER_TOKEN` 生成
- `INSTANCE_KEY_SECRET` 生成
- `SESSION_SECRET` 生成
- Docker Runner起動
- Webサービス起動
- Health Check

まで行います。

公開URL:

```text
http://127.0.0.1:8080
```

停止:

```powershell
.\stop-windows.ps1
```

## server.env

```bash
python server.py init-env
python server.py check
```

主な設定:

```text
BACKEND_PROVIDER=runner
APP_HOST=0.0.0.0
PORT=8080
DATABASE_URL=sqlite:///data/rental.db
SESSION_SECRET=<generated>
INSTANCE_KEY_SECRET=<generated>
RUNNER_TOKEN=<generated>
RUNNER_URL=http://127.0.0.1:9000
RUNNER_PUBLIC_BASE_URL=http://127.0.0.1
```

リモートRunnerの場合、`RUNNER_PUBLIC_BASE_URL` はDockerが公開したポートへブラウザから到達できるホスト名/IPに変更してください。

## Docker Compose

```bash
python server.py init-env
docker compose up -d --build
```

control側はDocker socketを持たず、RunnerだけがDocker Engineを操作します。

## Render公開

```text
Repository: https://github.com/ritsu1000000-maker/sandbox
Branch: rental-server-mvp
Root Directory: rental-server
Runtime: Python 3
Build Command: pip install -r requirements.txt
Start Command: gunicorn -c gunicorn.conf.py app_ext:app
Health Check Path: /health
```

Render ProviderはRender REST APIによるサービス発行用です。ユーザーがアップロードした任意Python/Node.jsプロジェクトのBuild/Start Command実行は、隔離Docker Runner Providerで行います。

## セキュリティ

- パスワードはWerkzeugのハッシュで保存
- Session CookieはHttpOnly
- CSRF Token必須
- Content Security Policy
- X-Content-Type-Options
- Referrer-Policy
- Permissions-Policy
- ユーザー所有権をDBで確認
- Provider API Keyはブラウザへ渡さない
- Docker socketはcontrolサービスへ渡さない
- 利用者へホストOSのシェルを直接公開しない
- 有料Providerリソースは支払い確認前に作成しない
- Environment Variablesは公開Project Filesと分離して保存
