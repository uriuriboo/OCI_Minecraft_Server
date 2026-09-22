# 07. 運用・トラブルシュート

保存先: `docs/07-operations.md`

## よく使うコマンド

```bash
ssh ubuntu@mc-server
cd ~/minecraft

docker compose logs -f                        # ログ
docker compose exec mc rcon-cli               # コンソール
docker compose restart                        # 再起動
docker compose pull && docker compose up -d   # イメージ更新

./backup.sh                                   # バックアップ
```

```bash
ssh ubuntu@mc-monitor

systemctl list-timers mc-monitor.timer        # 次回実行時刻
journalctl -u mc-monitor.service -f           # 監視ログ
sudo systemctl start mc-monitor.service       # 即時1回実行
```

## 定期的に確認すること

| 頻度 | 内容 |
|---|---|
| 随時 | バックアップ実行（手動） |
| 四半期 | 復元テスト |
| 随時 | イメージ更新 |
| 随時 | Always Free 枠（Arm が 2 OCPU/12GB 以内か） |
| 随時 | ディスク使用率のトレンド（Dashboards） |

## 仕上げ設定

### 自動更新

```bash
# 両VM
sudo apt install -y unattended-upgrades
sudo dpkg-reconfigure -plow unattended-upgrades
```

## ハマりどころ

| 症状 | 原因 | 対処 |
|---|---|---|
| Tailscale で繋がらない | Auth Key 期限切れ／cloud-init 失敗 | `enable_home_ssh=true` で一時復旧し `journalctl -u cloud-final` 確認 |
| Minecraft に繋がらない | iptables の DROP ルール | `iptables -L INPUT -n` で `tailscale0` の ACCEPT が上位にあるか |
| RCON 接続失敗 | host network での bind | `iptables -L INPUT -n` で VCN 内許可を確認 |
| メモリメトリクスが出ない | Cloud Agent の反映待ち | 10分程度待つ |
| ディスクメトリクスが取れない | `fileSystemName` の値違い | 実測値を monitor.py へ反映 |
| Monitoring API が 401 | 権限不足 | `read metrics` と `use metrics` の両方があるか |
| カスタムメトリクスが出ない | `use metrics` 権限なし | iam.tf に追加して apply |
| Arm VM 作成失敗 | Out of Capacity | `ad_index` を変える、時間をおく |
| TPS が取れない | PaperMC の出力形式 | 生出力を確認し正規表現を調整 |
| 友人が繋がらない | Tailscale ACL | `tag:friend` の付与とACL保存を確認 |

## 緊急時の入り口

Tailscale も SSH も使えなくなった場合、OCI コンソールから入れます。

コンソール → インスタンス詳細 → リソース → コンソール接続 → 「コンソール接続の作成」

シリアルコンソール経由で OS に直接ログインできます。この手段が残っているため、外部ポートを全て閉じても完全に詰むことはありません。

## 構成変更時の注意

### Minecraft の設定を変えたい

`~/minecraft/docker-compose.yml` を直接編集して `docker compose up -d` で反映されますが、Terraform の cloud-init とは乖離します。VM を作り直すと元に戻るため、恒久的な変更は cloud-init 側にも反映してください。

### 監視間隔を変えたい

`/etc/systemd/system/mc-monitor.timer` の `OnUnitActiveSec` を編集し、`daemon-reload` と `restart` を実行します。

### 閾値を変えたい

`monitor.py` の `THRESHOLDS` を編集するだけです。次回実行から反映されます。

## 将来的な拡張候補

| やりたいこと | 方法 |
|---|---|
| サーバー内部の設定管理を楽にしたい | Ansible を導入し cloud-init から移す |
| state をローカルに置きたくない | OCI Resource Manager へ移行 |
| ゲームログを検索したい | OCI Logging + Unified Monitoring Agent |
| バックアップを自動化したい | systemd タイマーを追加（常駐は増えない） |
| 監視を OCI 外から行いたい | 自宅 Pi5 に monitor.py を移設（APIキー認証に変更が必要） |

最初から抽象化を足すより、運用して不便を感じた時点で導入する方が手戻りが少ないです。