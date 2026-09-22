#!/bin/bash
# mc-server 上で実行する復元スクリプト。
#
#   scp scripts/restore.sh ubuntu@mc-server:~/
#   ssh ubuntu@mc-server
#   ~/restore.sh                    # R2 から一覧を取得して選ばせる
#   ~/restore.sh world-2026-09-21-0300.tgz
#
# バックアップは復元できて初めて機能する。構築直後に一度通しておくこと
# (docs/spec/09-verification.md の受入試験項目)。
set -euo pipefail

MC_DIR=/home/ubuntu/minecraft
BACKUP_DIR="$MC_DIR/backups"
R2_REMOTE="r2:minecraft-backup"

log() { echo "[$(date -Is)] $*"; }
die() { echo "ERROR: $*" >&2; exit 1; }

[ -d "$MC_DIR" ] || die "$MC_DIR がありません。mc-server 上で実行してください。"

ARCHIVE="${1:-}"

# ---------- 1. 復元元の決定 ----------
if [ -z "$ARCHIVE" ]; then
  log "R2 のバックアップ一覧:"
  rclone lsl "$R2_REMOTE" | sort -k2 || die "R2 に接続できません。rclone.conf を確認してください。"
  echo
  read -r -p "復元するファイル名を入力してください: " ARCHIVE
  [ -n "$ARCHIVE" ] || die "ファイル名が空です。"
fi

# ---------- 2. 取得 ----------
if [ ! -f "$BACKUP_DIR/$ARCHIVE" ]; then
  log "R2 から取得: $ARCHIVE"
  rclone copy "$R2_REMOTE/$ARCHIVE" "$BACKUP_DIR" --progress
fi
[ -f "$BACKUP_DIR/$ARCHIVE" ] || die "$BACKUP_DIR/$ARCHIVE がありません。"

# 壊れたアーカイブで上書きしないよう、展開前に中身を検証する
log "アーカイブを検証中..."
tar -tzf "$BACKUP_DIR/$ARCHIVE" >/dev/null || die "アーカイブが壊れています: $ARCHIVE"

# ---------- 3. 確認 ----------
echo
echo "以下を実行します:"
echo "  1. docker compose down          (サーバー停止)"
echo "  2. data → data.broken.<日時>    (現在のワールドを退避)"
echo "  3. $ARCHIVE を data へ展開"
echo "  4. docker compose up -d         (サーバー起動)"
echo
echo "現在のワールドは削除せず data.broken.<日時> に残します。"
read -r -p "続行しますか? [y/N] " ans
[ "$ans" = "y" ] || [ "$ans" = "Y" ] || die "中止しました。"

# ---------- 4. 復元 ----------
cd "$MC_DIR"
log "サーバー停止"
docker compose down

STAMP=$(date +%Y%m%d-%H%M%S)
if [ -d data ]; then
  log "現在のワールドを data.broken.$STAMP へ退避"
  mv data "data.broken.$STAMP"
fi

log "展開"
mkdir data
tar -xzf "$BACKUP_DIR/$ARCHIVE" -C ./data
chown -R ubuntu:ubuntu ./data

log "サーバー起動"
docker compose up -d

log "復元完了。起動ログを確認してください:"
echo "  cd $MC_DIR && docker compose logs -f"
echo
echo "問題なければ退避したワールドを削除できます:"
echo "  rm -rf $MC_DIR/data.broken.$STAMP"
