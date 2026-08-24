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

現状、Windows Docker Desktopでは容量値は契約プラン情報として管理しています。CPU/RAM制限はDockerへ実際に適用します。厳密な永続ディスククォータは別途ストレージ機構が必要です。

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

作成したサーバーの管理キーはブラウザのLocal Storageへ保存されます。管理キーを紛失すると、そのブラウザ以外から管理できません。

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

# 構成

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

各利用者用サーバーには管理キーのSHA-256だけをDockerラベルとして保存し、生の管理キーは保存しません。

# Renderについて

このリポジトリの現在のRunnerはDocker Engineを直接操作して利用者用コンテナを作る方式です。そのため、Web画面だけをRender Web Serviceへ置いても、Render上でそのままDocker Runner部分まで動かすことはできません。

Renderだけでレンタルサーバー生成まで完結させる場合は、RunnerをDocker SDK方式からRender API方式へ変更する必要があります。その場合は利用者の申し込みに応じてRender Serviceを作成・管理する構成へ変更します。

# 今後

- Render API Runner
- 決済完了後の有料プラン有効化
- ユーザーアカウント
- 永続ディスク容量クォータ
- 独自ドメイン
- HTTPS
- 利用期限
- CPU/RAMグラフ
- リアルタイムログ
