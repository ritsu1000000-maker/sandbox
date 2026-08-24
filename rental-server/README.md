# Rental Server

アカウント・契約・所有権・更新日・実サーバー発行を分離した、Python / Flask製のレンタルサーバー管理サービスです。

## 実装済みのレンタルフロー

```text
新規登録 / ログイン
        |
        v
料金プランを選択
        |
        v
契約を作成（契約ID / 更新日 / 所有者）
        |
        +-- 無料プラン ------> 即時プロビジョニング
        |
        +-- 有料プラン ------> pending_payment（決済確認待ち）
                                |
                                v
                        決済確認後に発行
        |
        v
Dashboard / Server Control
        |
        +-- Start
        +-- Stop
        +-- Restart
        +-- Public URL
        +-- 契約解約 -> 実サーバー削除
```

ブラウザLocalStorageの管理キーだけで所有者を判定する方式は廃止し、ログイン中のユーザーIDと契約DBで所有権を確認します。

## 構成

```text
Browser
  |
  v
Flask Web / Session / CSRF
  |
  +--> RentalDatabase
  |      +-- SQLite (local)
  |      +-- PostgreSQL (production)
  |
  v
RentalService
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
├─ server.py
├─ server.env.example
├─ .env.example
├─ gunicorn.conf.py
├─ runner.py
├─ rental_core/
│  ├─ config.py
│  ├─ database.py
│  ├─ env_loader.py
│  ├─ errors.py
│  ├─ manager.py
│  ├─ providers.py
│  ├─ rate_limit.py
│  ├─ rental_service.py
│  └─ security.py
├─ templates/
└─ static/
```

# Webページ

| URL | 内容 |
| --- | --- |
| `/` | トップ |
| `/plans` | 契約プラン比較 |
| `/signup` | 契約者アカウント作成 |
| `/login` | ログイン |
| `/dashboard` | 自分の契約一覧 |
| `/create` | 新規契約 |
| `/servers/<contract_id>` | 契約中サーバー管理 |
| `/billing` | 契約・月額・更新日 |
| `/health` | 稼働確認 |
| `/api/system` | システム状態 |

`/create`、`/dashboard`、`/servers/<contract_id>`、`/billing`はログイン必須です。

# 所有権

ユーザーが入力するサーバー表示名と、Provider内部の名前は分離しています。

例:

```text
表示名: my-server
内部名: u12-my-server-a1b2c3
```

そのため、別ユーザーが同じ `my-server` という表示名を契約してもProvider側では衝突しません。

サーバー操作時は:

1. ログインセッション確認
2. `contract_id` がログインユーザー所有かDBで確認
3. 内部resource nameからProvider管理キーをサーバー側で導出
4. Render / Runnerへ操作

という順で処理します。Provider管理キーはブラウザへ保存しません。

# 契約状態

| 状態 | 意味 |
| --- | --- |
| `pending_payment` | 有料契約・決済確認待ち |
| `provisioning` | 実サーバー発行中 |
| `active` | 利用中 |
| `provision_failed` | 発行失敗 |
| `canceled` | 解約済み |

無料プランは契約作成後に即時プロビジョニングします。

有料プランは決済確認なしでRenderの有料サービスを作成しないため、まず `pending_payment` で保存します。

# データベース

## ローカル

デフォルト:

```text
DATABASE_URL=sqlite:///data/rental.db
```

SQLiteには以下を保存します。

- ユーザーID
- メールアドレス
- パスワードハッシュ
- 契約ID
- 契約者ID
- 表示サーバー名
- Provider内部名
- プラン
- 実行環境
- 契約状態
- 公開URL
- 契約日
- 次回更新日
- 解約日

`data/` と `*.db` は `.gitignore` 済みです。

## 本番

`DATABASE_URL` が `postgresql://` / `postgres://` なら自動的にPostgreSQLを使用します。

```text
DATABASE_URL=postgresql://...
```

Renderなどの再デプロイがある環境ではPostgreSQLを推奨します。

現在のRender WorkspaceではHobby Tierの25サービス上限に達しているため、新しい無料PostgreSQLの作成がRender APIから拒否されます。空き枠を作るか別の永続PostgreSQLを用意した後、`DATABASE_URL`を差し替えればコード変更なしで移行できます。

# server.env

初回:

```powershell
python server.py init-env
```

主要項目:

```text
BACKEND_PROVIDER=runner
APP_HOST=0.0.0.0
PORT=8080
CREATE_LIMIT_PER_HOUR=10
LEASE_DAYS=30

SESSION_SECRET=<自動生成>
INSTANCE_KEY_SECRET=<自動生成>
DATABASE_URL=sqlite:///data/rental.db

RUNNER_HOST=127.0.0.1
RUNNER_PORT=9000
RUNNER_URL=http://127.0.0.1:9000
RUNNER_TOKEN=<自動生成>
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

`SESSION_SECRET`、`INSTANCE_KEY_SECRET`、`RUNNER_TOKEN`、`RENDER_API_KEY`は公開しないでください。

# Windows / Docker Runner

必要:

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

初回は `.venv`、依存パッケージ、`server.env`、秘密値、SQLite DBを自動準備します。

停止:

```powershell
.\stop-windows.ps1
```

# Render公開

Web Service:

```text
Repository: https://github.com/ritsu1000000-maker/sandbox
Branch: rental-server-mvp
Root Directory: rental-server
Build Command: pip install -r requirements.txt
Start Command: gunicorn app:app --bind 0.0.0.0:$PORT
Health Check Path: /health
```

Environment:

```text
BACKEND_PROVIDER=render
RENDER_API_KEY=<secret>
RENDER_OWNER_ID=<workspace id>
INSTANCE_KEY_SECRET=<secret>
DATABASE_URL=<PostgreSQL URL recommended>
LEASE_DAYS=30
ALLOW_PAID_RENDER_PLANS=false
```

`SESSION_SECRET`を独立して設定するのが推奨ですが、未設定時は`INSTANCE_KEY_SECRET`をログインセッション署名にも使用します。

# セキュリティ

- パスワードはWerkzeugのパスワードハッシュで保存
- セッションCookieはHttpOnly / SameSite=Lax
- Render上ではSecure Cookie
- POST操作はCSRF token必須
- Content Security Policy / nosniff / Referrer Policy
- 契約所有権をDBで確認
- Render API Keyはブラウザへ送らない
- Provider管理キーはブラウザへ保存しない
- controlへDocker socketを渡さない
- RunnerのみDocker Engineを操作
- 利用者へホストOSのcmd.exeやDocker socketを公開しない
- 有料プランは決済確認前に実サーバーを発行しない

# プラン

| 容量 | 月額 | RAM | CPU |
| ---: | ---: | ---: | ---: |
| 500MB | 無料 | 128MB | 0.1 |
| 1GB | 500円 | 256MB | 0.25 |
| 10GB | 1,500円 | 512MB | 0.5 |
| 50GB | 2,000円 | 1GB | 1.0 |
| 100GB | 4,000円 | 2GB | 2.0 |

注意: Render APIモードで表示しているStorage/RAM/CPUは契約プラン情報です。実際の永続ディスククォータやRenderインスタンスタイプと完全一致させるには、Provider側の容量割当・永続ディスク管理を追加する必要があります。

# 次の本番機能

契約・所有権・ログイン・DB・自動発行のコアは実装済みです。商用の有料運営まで進める場合に残る大きな項目は以下です。

- 決済プロバイダWebhookによる `pending_payment -> active` 自動化
- メールアドレス確認
- パスワード再設定
- 実永続ディスク容量クォータ
- バックアップ/復旧
- 契約期限切れの自動停止
- 共有Redisレート制限
