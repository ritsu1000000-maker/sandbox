# Hosting Service

Python / Flask を中心にした、アカウント型のアプリケーションホスティングサービスです。

利用者はアカウントを作成し、ホスティングプランと実行環境を選んで、自分専用のサービスを発行・管理できます。

## 主な機能

- アカウント登録 / ログイン
- ユーザーごとのサービス所有権管理
- 500MB〜100GBのホスティングプラン
- Python Web / Node.js Web / Nginx
- Render Provider / Docker Runner Provider
- Start / Stop / Restart
- 公開URL
- プラン・月額・更新予定の管理
- 無料プランの即時発行
- 有料プランの支払い確認待ち状態
- Render容量不足時の `capacity_waiting`
- SQLite / PostgreSQL対応
- CSRF / Session / Security Headers

## 利用フロー

```text
アカウント作成
      |
      v
ホスティングプランを選択
      |
      v
サービス名・Runtimeを設定
      |
      +-- 無料プラン ---> 即時プロビジョニング
      |
      +-- 有料プラン ---> pending_payment
      |
      v
Hosting Dashboard
      |
      +-- Public URL
      +-- Start
      +-- Stop
      +-- Restart
      +-- Plan / Billing
      +-- 利用終了
```

## アーキテクチャ

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

`RentalDatabase` / `RentalService` / `/api/contracts` という内部名は既存データ・API互換性のため残しています。利用者向けUIでは Hosting Service / Service / Plan として表示します。

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
| `/billing` | プラン・請求 |
| `/health` | 稼働確認 |
| `/api/system` | システム情報 |

## プラン

| Storage | 月額 | RAM | CPU |
| ---: | ---: | ---: | ---: |
| 500MB | ¥0 | 128MB | 0.1 |
| 1GB | ¥500 | 256MB | 0.25 |
| 10GB | ¥1,500 | 512MB | 0.5 |
| 50GB | ¥2,000 | 1GB | 1.0 |
| 100GB | ¥4,000 | 2GB | 2.0 |

表示している Storage / RAM / CPU はホスティングサービス側のプラン値です。Provider側で実際に適用できる上限とは分けて管理します。

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

`server.env.example` から生成します。

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
```

Render Providerを使う場合:

```text
BACKEND_PROVIDER=render
RENDER_API_KEY=<secret>
RENDER_OWNER_ID=<workspace id>
RENDER_TENANT_REPO=https://github.com/ritsu1000000-maker/sandbox
RENDER_TENANT_BRANCH=rental-server-mvp
RENDER_TENANT_REGION=singapore
RENDER_SERVICE_PREFIX=rental
ALLOW_PAID_RENDER_PLANS=false
```

`server.env` / `.env` / SQLite本番データはGit管理しません。

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
Start Command: gunicorn -c gunicorn.conf.py app:app
Health Check Path: /health
```

最低限のEnvironment Variables:

```text
BACKEND_PROVIDER=render
RENDER_API_KEY=<Render API Key>
RENDER_OWNER_ID=<Render Workspace ID>
INSTANCE_KEY_SECRET=<long random secret>
DATABASE_URL=<production database URL>
```

## セキュリティ

- パスワードはWerkzeugのハッシュで保存
- Session CookieはHttpOnly
- CSRF Token必須
- Content Security Policy
- X-Content-Type-Options
- Referrer-Policy
- Permissions-Policy
- ユーザー所有権をDBで確認
- Render API Keyはブラウザへ渡さない
- Docker socketはcontrolサービスへ渡さない
- 利用者へホストOSのシェルを直接公開しない
- 有料Providerリソースは支払い確認前に作成しない

## 本番運用で追加したい機能

- 永続PostgreSQL
- 実決済連携
- メール認証 / パスワードリセット
- Custom Domain / DNS verification
- CPU / RAM / Request metrics
- 実ストレージクォータ
- バックアップ / 復元
- 管理者向けサービス管理画面
- Abuse protection / CAPTCHA / shared rate limit
