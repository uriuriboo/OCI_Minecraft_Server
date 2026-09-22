<!-- このページは docs/spec/06-operations.md から生成しています。直接編集しないでください。
     修正は docs/spec/ 側に入れて `python scripts/sync-wiki.py` を実行してください。 -->

# 06. 運用・保守

## 変更管理: どこを変えるか

**これが本構成で最も間違えやすい部分である。** 変更対象によって触る場所が違い、間違えるとワールドが消える。

| 変えたいもの | 触る場所 | 適用方法 | VM 再作成 |
| --- | --- | --- | --- |
| ホワイトリスト / OP / プラグイン | `terraform.tfvars` の `mc_whitelist` 等 | `terraform apply` → Ansible `-t app` | されない |
| MEMORY / MOTD / 難易度 / 視距離 | `terraform.tfvars` の `mc_*` | 同上 | されない |
| playit シークレットキー | `terraform.tfvars` の `playit_secret_key` | 同上 | されない |
| mc-router の接続レート / scale to zero | `terraform.tfvars` の `mc_router_*` | 同上 | されない |
| 監視の閾値 / `FILESYSTEM_NAME` | `terraform.tfvars` の `monitor_thresholds` / `filesystem_name` | `terraform apply` → Ansible `-t monitor` | されない |
| monitor.py のロジック | `monitor/monitor.py` | Ansible `-t monitor` | されない |
| 監視の実行間隔 | `monitor/systemd/mc-monitor.timer` | Ansible `-t monitor` | されない |
| NSG / SSH 穴 / サブネット | `terraform/network.tf`、`enable_home_ssh` | `terraform apply` | されない |
| バックアップ保持世代 | `terraform.tfvars` の `backup_*` | `terraform apply` → cloud-init 再実行が必要 | **要注意** (下記) |
| iptables / パッケージ / Tailscale 参加 | `terraform/cloud-init/*` | **VM 再作成が必要** | **される** |
| `exposure_mode` の切り替え | `terraform.tfvars` | 下記の手順 | 部分的 |
| Tailscale ACL | `tailscale/acl.hujson` | 管理画面に貼る | されない |
| ダッシュボード | `dashboards/oci-dashboard.json` | コンソールで手入力 | されない |

### なぜ cloud-init の変更が VM 再作成になるのか

OCI では `metadata.user_data` の変更がインスタンス置換を引き起こす。置換はブートボリュームの破棄 = **ワールド消失**を意味する。

これを防ぐため、両インスタンスに `lifecycle { ignore_changes = [metadata, ...] }` を付けている。**tfvars を変えても VM は作り直されない**。

副作用として、cloud-init に閉じた変更 (iptables ルール、パッケージ追加) は既存 VM に反映されない。反映させたい場合の選択肢は3つある。

| 選択肢 | 手順 | ワールド |
| --- | --- | --- |
| 1. 手で入れる (推奨) | SSH して `iptables` / `apt install` を直接実行 | 安全 |
| 2. VM を作り直す | バックアップ → `terraform apply -replace=oci_core_instance.mc_server` → 復元 | **復元が必須** |
| 3. Ansible の対象に追加する | `site.yml` にタスクを足す | 安全。恒久的な運用なら妥当 |

選択肢1を採った場合、cloud-init のコードも合わせて更新しておくこと。次に VM を作り直した時に設定が戻ってしまうため。

### `exposure_mode` の切り替え手順

`docker-compose.yml` と iptables を書き換えるだけで、**ワールドデータには影響しない**。

`playit` に切り替えたとき、または `playit` から離れるときは、playit.gg 側のトンネル設定も合わせる。`playit` では Local address が **`mc-router:25565`** (`mc:25565` ではない)。

```bash
# 1. exposure_mode を変更
cd terraform && terraform apply

# 2. docker-compose.yml を配送して再起動
cd ../ansible && ansible-playbook site.yml -t app

# 3. iptables は cloud-init 側にあるため手で入れる
ssh ubuntu@mc-server
#   playit → tailscale の場合
sudo iptables -I INPUT -i tailscale0 -p tcp --dport 25565 -j ACCEPT
sudo iptables -A INPUT -p tcp --dport 25565 -j DROP
sudo iptables -I INPUT -s 10.0.1.0/24 -p tcp --dport 25575 -j ACCEPT
sudo iptables -A INPUT -p tcp --dport 25575 -j DROP
sudo netfilter-persistent save
sudo iptables -L INPUT -n --line-numbers      # ACCEPT が DROP より上か確認
```

## よく使うコマンド

### mc-server

```bash
ssh ubuntu@mc-server
cd ~/minecraft

docker compose logs -f                        # ログ
docker compose logs -f mc-router              # 経路 (playit 方式のみ)
docker compose exec mc rcon-cli               # コンソール
docker compose restart                        # 再起動
docker compose pull && docker compose up -d   # イメージ更新
./backup.sh                                   # バックアップ
```

### mc-monitor

```bash
ssh ubuntu@mc-monitor

systemctl list-timers mc-monitor.timer        # 次回実行時刻
journalctl -u mc-monitor.service -f           # 監視ログ
sudo systemctl start mc-monitor.service       # 即時1回実行
```

### 管理端末

```bash
cd terraform && terraform apply               # インフラ + ansible/files/ の更新
cd ansible && ansible-playbook site.yml -t app --check    # 差分確認
cd ansible && ansible-playbook site.yml -t app            # 適用
uv run scripts/check-consistency.py           # 設定の整合性検査
uv run scripts/print-dashboard.py             # ダッシュボード用 MQL

# monitor.py の依存を変えたとき (pyproject.toml → requirements.txt)
uv pip compile pyproject.toml --group monitor --python-version 3.12 --python-platform x86_64-unknown-linux-gnu -o monitor/requirements.txt
```

ツールの導入は [A2. ツール導入](Spec-A2-toolchain) を参照。Terraform は tenv で、Python は uv で管理する。

VS Code の `.vscode/tasks.json` に同じものを登録している (`Ctrl+Shift+P` → Tasks: Run Task)。

## 定期的に確認すること

| 頻度 | 内容 | 確認方法 |
| --- | --- | --- |
| 遊ぶ前後 | バックアップ実行 | `./backup.sh` |
| 随時 | ディスク使用率のトレンド | ダッシュボード |
| 月次 | イメージ更新 | `docker compose pull && docker compose up -d` |
| 月次 | Always Free 枠の逸脱がないか | コンソール → 請求 |
| 四半期 | **復元テスト** | `restore.sh` を実際に通す |
| 四半期 | Tailscale ノードのキー期限が無効か | 管理画面 → Machines |
| 半期 | バージョン更新の検討 | [07. 構成技術・バージョン](Spec-07-tech-stack) |

OS の更新は `unattended-upgrades` が自動で行うため手作業は不要である (cloud-init で `/etc/apt/apt.conf.d/20auto-upgrades` を配置済み)。

## Ansible の実行環境

Ansible は **Windows をコントロールノードとしてサポートしない**。以下のいずれかから実行する。

| 実行場所 | 準備 | 備考 |
| --- | --- | --- |
| WSL2 (推奨) | `apt install ansible-core`、WSL 側にも Tailscale と `~/.ssh` | 管理端末で完結する |
| mc-monitor | 既に tailnet 内。`uv tool install ansible-core` | リポジトリを持ち込む必要がある |
| Ansible を使わない | `scripts/deploy-monitor.sh` | monitor 更新のみ。scp + systemctl の最小版 |

`ansible.builtin.systemd_service` モジュールを使うため ansible-core に下限がある。値は [07. 構成技術・バージョン](Spec-07-tech-stack)、導入手順は [A2. ツール導入](Spec-A2-toolchain)。

VM 側の Python は uv で管理しており `pip` を入れていない。そのため `site.yml` では `ansible.builtin.pip` モジュールではなく `uv pip sync` を直接呼んでいる。

## 障害対応

### 切り分けの順序

```text
Minecraft に繋がらない
  │
  ├─ 管理者は SSH できるか?
  │    NO → 「SSH できない」へ
  │    YES ↓
  │
  ├─ docker compose ps で mc が Up か?
  │    NO → docker compose logs で起動失敗の原因を見る
  │    YES ↓
  │
  ├─ exposure_mode は?
  │    playit    → docker compose ps で mc-router と playit が Up か
  │                 playit.gg のトンネルの Local address が mc-router:25565 か
  │    tailscale → iptables -L INPUT -n で ACCEPT が DROP より上か / ACL
  │    zerotier  → zerotier-cli listnetworks で OK か / 管理画面の承認
  │    ↓
  │
  └─ ホワイトリストに MCID が入っているか?
       docker compose exec mc rcon-cli whitelist list
```

### SSH できない

```text
1. Tailscale で繋がらない
   → 管理画面で mc-server が表示されているか
   → ノードのキー期限が切れていないか (Disable key expiry を確認)
   → Auth Key の期限切れなら、シリアルコンソールから tailscale up をやり直す

2. 一時復旧: enable_home_ssh=true にして terraform apply
   → ssh -i ~/.ssh/oci_mc ubuntu@$(terraform output -raw minecraft_public_ip)
   → journalctl -u cloud-final で cloud-init の失敗を確認

3. どちらも駄目な場合: OCI シリアルコンソール
   コンソール → インスタンス詳細 → リソース → コンソール接続 → コンソール接続の作成
```

**この3段目が残っているため、外部ポートを全て閉じても完全に詰むことはない。**

### 症状別の対処

| 症状 | 原因 | 対処 |
| --- | --- | --- |
| Tailscale で繋がらない | Auth Key 期限切れ / cloud-init 失敗 | `enable_home_ssh=true` で一時復旧し `journalctl -u cloud-final` |
| Minecraft に繋がらない (tailscale/zerotier) | iptables の順序 | `iptables -L INPUT -n --line-numbers` で ACCEPT が上位か |
| Minecraft に繋がらない (playit) | トンネル停止 | `docker compose ps playit` / `docker compose logs playit` |
| Minecraft に繋がらない (playit、playit は Up) | mc-router 停止 / トンネルの転送先違い | `docker compose logs mc-router` / Local address が `mc-router:25565` か |
| 接続が時々だけ弾かれる (playit) | 接続レート制限 | `mc_router_rate_limit` を上げる |
| RCON 接続失敗 | NSG / iptables / コンテナ停止 | `nc -zv 10.0.1.10 25575` を mc-monitor から |
| メモリメトリクスが出ない | Cloud Agent の反映待ち | 10分程度待つ |
| ディスクメトリクスが取れない | `fileSystemName` の値違い | 実測値を `filesystem_name` に反映 |
| Monitoring API が 401 | 権限不足 | `read metrics` と `use metrics` の両方があるか |
| カスタムメトリクスが出ない | `use metrics` 権限なし | `iam.tf` を apply |
| Arm VM 作成失敗 | Out of Capacity | `ad_index` を 1, 2 に変える / 時間をおく |
| TPS が取れない | PaperMC の出力形式 | 生出力を確認して `monitor.py` の正規表現を調整 |
| 友人が繋がらない (tailscale) | ACL | `group:mc-friends` にメールアドレスがあるか |
| 友人が繋がらない (playit) | ホワイトリスト | `mc_whitelist` に MCID があるか |
| Discord に通知が来ない | Webhook / タイマー停止 | `systemctl list-timers` / `journalctl -u mc-monitor.service` |
| バックアップが失敗する | RCON / rclone / 権限 | `backup.sh` を手で実行して出力を見る |

### Out of Capacity のリトライ

Arm 枠は競争率が高く、初回で通らないことがよくある。

```bash
terraform apply -var="ad_index=1"
terraform apply -var="ad_index=2"

# または時間をおいてリトライ
until terraform apply -auto-approve; do
  echo "retrying in 5min..."
  sleep 300
done
```

## 将来の拡張候補

| やりたいこと | 方法 | 判断の目安 |
| --- | --- | --- |
| バックアップを自動化したい | systemd タイマーを追加 (常駐は増えない) | 手動を忘れるようになったら |
| 無人時に mc を止めてメモリを空けたい | `mc_router_auto_scale = true`。ただし先に monitor.py の死活判定を RCON から `mc-router:25565` への status ping に変える必要がある ([04. 監視](Spec-04-monitoring)) | mc-server で他のものを動かしたくなったら |
| サーバー内部の設定管理をもっと楽にしたい | Ansible の担当範囲を広げる | cloud-init を手で直す機会が増えたら |
| state をローカルに置きたくない | OCI Resource Manager へ移行 | 複数人で管理するようになったら |
| 秘密を tfvars から出したい | OCI Vault | 同上 |
| ゲームログを検索したい | OCI Logging + Unified Monitoring Agent | 荒らしの調査が必要になったら |
| 監視を OCI 外から行いたい | 自宅 Pi に monitor.py を移設 (APIキー認証へ変更) | OCI 全体障害も検知したくなったら |

**最初から抽象化を足すより、運用して不便を感じた時点で導入する方が手戻りが少ない。**
