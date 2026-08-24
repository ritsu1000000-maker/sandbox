# Rental Server

Python / Flaskを中心にしたレンタルサーバー管理サイトです。利用者はプランと実行環境を選び、自分専用のサーバーを作成・起動・停止・再起動・削除できます。

## 現在の構成

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
  +-- RunnerProvider ----> Docker Runner
```

`app.py` にはWeb/APIルートだけを置き、実際のプロバイダー操作・設定・管理キー・レート制限は `rental_core/` に分離しています。

```text
rental-server/
├─ app.py
├─ rental_core/
│  ├─ config.py
│  ├─ errors.py
│  ├─ manager.py
│  ├─ providers.py
│  ├─ rate_limit.py
│  └─ security.py
├─ templates/
├─ static/
├─ runner.py
└─ tenant_*
```

## Webページ

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

サーバー詳細画面では、状態、プラン、RAM、CPU、実行環境、Service ID、リージョン、公開URL、Start / Stop / Restart / Logs / Delete を確認・操作できます。

## プラン

| 容量 | 月額 | RAM | CPU |
| ---: | ---: | ---: | ---: |
| 500MB | 無料 | 128MB | 0.1 |
| 1GB | 500円 | 256MB | 0.25 |
| 10GB | 1,500円 | 512MB | 0.5 |
| 50GB | 2,000円 | 1GB | 1.0 |
| 100GB | 4,000円 | 2GB | 2.0 |

表示容量・RAM・CPUはレンタルサイト側のプラン情報です。Render APIモードではRenderの実際のインスタンスタイプや永続ディスクとは別管理です。Windows Docker RunnerモードではCPU/RAM制限をDockerへ適用します。

## 管理キー

管理者ログイン方式ではなく、サーバーごとに管理キーを使います。キーは利用者のブラウザLocal Storageへ保存されます。

Render APIモードでは `INSTANCE_KEY_SECRET` を使ったHMACで管理キーを生成し、APIキーそのものは利用者へ渡しません。

## 作成回数制限

公開APIの連続作成を抑えるため、サーバー作成APIに軽量なIP単位のレート制限があります。

```text
CREATE_LIMIT_PER_HOUR=10
```

デフォルトは1時間10回です。これは単一プロセス内の簡易制限なので、大規模運用ではRedis等の共有ストアへ置き換えてください。

# Render公開

RenderではDocker Runnerへ接続せず、Render REST APIを使います。

## Web Service設定

```text
Repository: https://github.com/ritsu1000000-maker/sandbox
Branch: rental-server-mvp
Root Directory: rental-server
Language: Python 3
Build Command: pip install -r requirements.txt
Start Command: gunicorn app:app --bind 0.0.0.0:$PORT
Health Check Path: /health
```

## Environment Variables

`.env` は不要です。Render DashboardのEnvironment Variablesに設定します。

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
CREATE_LIMIT_PER_HOUR=10
```

`RENDER_API_KEY` と `INSTANCE_KEY_SECRET` はGitHubへコミットしないでください。

## 有料プラン

初期状態ではRender APIから500MB無料プランだけ自動作成できます。

```text
ALLOW_PAID_RENDER_PLANS=false
```

有料Renderサービスを匿名利用者が自由に作成すると運営側に料金が発生する可能性があるため、決済確認を実装するまでは無効です。

# Windows / Docker Runner

必要なもの:

- Windows 10 / 11
- Docker Desktop
- Linux containersモード
- Python 3
- PowerShell

起動:

```powershell
cd rental-server
.\start-windows.ps1
```

停止:

```powershell
.\stop-windows.ps1
```

RunnerはDocker Engineを操作しますが、利用者へホストOSの `cmd.exe`、Docker socket、privileged container、host filesystemを直接公開しない設計です。

# 次に本格化する候補

- Renderの実ログ取得
- PostgreSQLによるユーザー・契約・監査ログ
- メール認証付きユーザーアカウント
- 決済確認後だけ有料プランを有効化
- 永続ディスク容量の実クォータ
- 独自ドメイン管理
- CPU / RAM / リクエスト数グラフ
- 利用期限・自動停止
- 管理キーの再発行・リカバリー
- Redisベースの共有レート制限
