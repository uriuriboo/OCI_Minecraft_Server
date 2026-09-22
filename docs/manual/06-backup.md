# 06. バックアップ

## 方針

常駐プロセスを持たず、実行したい時だけコンテナを起動して終了後に破棄します。`itzg/mc-backup` が RCON 経由で save-off → save-all → バックアップ → save-on を内部的に行うため、セーブ制御を自前で書く必要がありません。

## 1. rclone 設定（初回のみ）

```bash
ssh ubuntu@mc-server
rclone config
```

対話で入力する項目:

| 項目 | 値 |
|---|---|
| name | `r2` |
| type | `s3` |
| provider | `Cloudflare` |
| access_key_id | R2のAccess Key ID |
| secret_access_key | R2のSecret Access Key |
| endpoint | `https://<account-id>.r2.cloudflarestorage.com` |

```bash
# 疎通確認
rclone lsd r2:
```

## 2. バックアップスクリプト

```bash
nano ~/minecraft/backup.sh
```

```bash
#!/bin/bash
set -euo pipefail

source /home/ubuntu/minecraft/.env

echo "[$(date -Is)] backup start"

docker run --rm \
  --network container:mc \
  -e RCON_HOST=localhost \
  -e RCON_PORT=25575 \
  -e RCON_PASSWORD="${RCON_PASSWORD}" \
  -v /home/ubuntu/minecraft/data:/data:ro \
  -v /home/ubuntu/minecraft/backups:/backups \
  itzg/mc-backup \
  backup now

rclone sync /home/ubuntu/minecraft/backups r2:minecraft-backup --progress

echo "[$(date -Is)] backup done"
```

```bash
chmod +x ~/minecraft/backup.sh
```

`--network container:mc` は `mc` コンテナのネットワーク名前空間を共有する指定です。これにより `localhost:25575` で RCON に到達します。

`--rm` により実行後にコンテナは自動削除されます。イメージ本体（数十MB）はホストに残り、次回の起動が速くなります。

## 3. 実行

```bash
~/minecraft/backup.sh
```

平常時は `docker ps` に `mc` しか表示されません。バックアップ中だけ一時的にコンテナが現れます。

## 4. 復元

```bash
cd ~/minecraft

# R2から取得
rclone copy r2:minecraft-backup ./backups --progress
ls -la ./backups

# サーバー停止
docker compose down

# 展開
mv data data.broken
mkdir data
tar -xzf ./backups/<バックアップファイル名>.tgz -C ./data
chown -R ubuntu:ubuntu ./data

docker compose up -d
```

**構築直後に一度試してください。** バックアップは復元できて初めて機能します。

## 5. 圧縮方式の変更（任意）

デフォルトは tar 方式で、世代ごとにほぼフルサイズになります。容量が気になる場合は rsync 方式（差分）に変更できます。

```bash
docker run --rm \
  --network container:mc \
  -e BACKUP_METHOD=rsync \
  -e RCON_HOST=localhost \
  -e RCON_PORT=25575 \
  -e RCON_PASSWORD="${RCON_PASSWORD}" \
  -v /home/ubuntu/minecraft/data:/data:ro \
  -v /home/ubuntu/minecraft/backups:/backups \
  itzg/mc-backup \
  backup now
```

## 6. バックアップ先の選択について

| | Cloudflare R2 | OCI Object Storage |
|---|---|---|
| 容量 | 10GB 無料 | 20GB 無料 |
| APIリクエスト | 月100万回 | 月5万回 |
| 冗長性 | 別事業者 | サーバーと同一事業者 |

R2 を選んでいる理由は、リクエスト数に余裕があること、そして**サーバーとバックアップを別事業者に分けられる**ことです。両方 OCI に置くと、アカウント停止やリージョン障害で同時に失われます。

## チェックリスト

```
[ ] rclone 設定
[ ] backup.sh 配置
[ ] 手動実行テスト
[ ] 復元テスト実施（重要）
```