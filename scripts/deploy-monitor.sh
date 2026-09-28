#!/bin/bash
# Ansible を使わずに monitor.py と .env を差し替える最小版。
#
# Ansible は Windows をコントロールノードにできないため、WSL2 を用意していない
# 環境向けのフォールバック。やっていることは ansible/site.yml の monitor タグと同じ。
#
#   ./scripts/deploy-monitor.sh
#
# 前提:
#   - Tailscale 経由で `ssh ubuntu@mc-monitor` が通ること (鍵の指定は不要)
#   - terraform apply 済みで ansible/files/mc-monitor.env が生成されていること
set -euo pipefail

HOST="${MONITOR_HOST:-mc-monitor}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="$ROOT/ansible/files/mc-monitor.env"

log() { echo "[$(date -Is)] $*"; }
die() { echo "ERROR: $*" >&2; exit 1; }

[ -f "$ROOT/monitor/monitor.py" ] || die "monitor/monitor.py がありません。"
[ -f "$ENV_FILE" ] || die "$ENV_FILE がありません。先に \`cd terraform && terraform apply\` を実行してください。"

log "monitor.py と依存定義を配送: $HOST"
scp -q "$ROOT/monitor/monitor.py" "$ROOT/monitor/requirements.txt" "ubuntu@$HOST:/home/ubuntu/"

log ".env を配送 (0600)"
scp -q "$ENV_FILE" "ubuntu@$HOST:/home/ubuntu/.env"
ssh "ubuntu@$HOST" 'chmod 600 /home/ubuntu/.env'

log "systemd unit を配送"
scp -q "$ROOT/monitor/systemd/mc-monitor.service" "$ROOT/monitor/systemd/mc-monitor.timer" "ubuntu@$HOST:/tmp/"
ssh "ubuntu@$HOST" 'sudo install -m 0644 -o root -g root /tmp/mc-monitor.service /tmp/mc-monitor.timer /etc/systemd/system/ && rm -f /tmp/mc-monitor.service /tmp/mc-monitor.timer'

log "依存を同期 (uv)"
ssh "ubuntu@$HOST" 'uv pip sync -q --python /home/ubuntu/venv/bin/python /home/ubuntu/requirements.txt'

# daemon-reload をしないと古い unit のまま動き続ける
log "タイマーを張り直して単発実行"
ssh "ubuntu@$HOST" 'sudo systemctl daemon-reload && sudo systemctl enable --now mc-monitor.timer && sudo systemctl restart mc-monitor.service'

log "直近のログ:"
ssh "ubuntu@$HOST" 'journalctl -u mc-monitor.service -n 20 --no-pager'

log "次回実行時刻:"
ssh "ubuntu@$HOST" 'systemctl list-timers mc-monitor.timer --no-pager'
