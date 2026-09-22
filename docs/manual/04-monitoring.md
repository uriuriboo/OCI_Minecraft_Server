# 04. 監視・通知（monitor.py）

## 役割

```
1. 読む
   ├─ RCON → TPS、プレイヤー数、死活
   └─ OCI Monitoring API → CPU、メモリ、ディスク

2. 判定する
   └─ 閾値と比較し、状態変化を検出

3. 書く
   ├─ Discord Webhook → アラート通知
   └─ OCI Monitoring API → TPS/プレイヤー数を記録（Dashboards用）
```

CPU・メモリ・ディスクは Oracle Cloud Agent が自動収集するため、monitor.py を止めてもそちらは動き続けます。TPS・プレイヤー数・Discord通知だけが止まります。

## monitor.py

実装の正は [monitor/monitor.py](../../monitor/monitor.py)。ここにあった全文コピーは削除した。二重管理になり、実際に `RCON_PORT` の読み方が実装とずれていた（`02-terraform.md` のコードを削除したのと同じ理由）。

| 知りたいこと | 参照 |
| --- | --- |
| 読む環境変数と既定値 | [08-parameters.md](../spec/08-parameters.md) |
| 閾値・状態遷移・カスタムメトリクスの設計 | [04-monitoring.md](../spec/04-monitoring.md) |
| VM への配り方 | [06-operations.md](../spec/06-operations.md)（Ansible の `monitor` タグ） |

`FILESYSTEM_NAME` は `03-post-setup.md` の手順8で確認した実測値を `terraform.tfvars` の `filesystem_name` に入れる。コードは書き換えない。

閾値を超え続けている間は毎回通知せず、状態が変化した時だけ送ります。

## 配置

初回構築は cloud-init が配置します。更新は Ansible で配ります。

```bash
cd ansible && ansible-playbook site.yml -t monitor
```

手で入れる場合は `scp monitor/monitor.py ubuntu@mc-monitor:/home/ubuntu/`。Tailscale 経由なので鍵指定は不要です。

## 強制発火テスト

閾値はコードではなく `/home/ubuntu/.env` の `THRESHOLD_*` から読みます。

```bash
ssh ubuntu@mc-monitor
# /home/ubuntu/.env の THRESHOLD_CPU を一時的に 0.0 にする
~/venv/bin/python3 ~/monitor.py
```

Discord に届いたら閾値を戻します。

## カスタムメトリクス送信の確認

コンソール → 監視 → メトリクス・エクスプローラ

| 項目 | 値 |
|---|---|
| ネームスペース | `custom_minecraft` |
| メトリック名 | `TPS`, `PlayerCount`, `ServerOnline` |

5分に1回しか送信していないため、データポイントが疎らに見えるのは正常です。

401 が出る場合は `iam.tf` の `use metrics` 権限が適用されているか確認してください。

## タイマー有効化

```bash
sudo systemctl enable --now mc-monitor.timer
systemctl list-timers mc-monitor.timer
journalctl -u mc-monitor.service -f
```

| コマンド | 用途 |
|---|---|
| `enable --now` | 自動起動設定 + 即時起動（初回のみ） |
| `list-timers` | 次回実行時刻の確認 |
| `journalctl -f` | 実行ログをリアルタイム表示 |

## 実行方式について

常駐プロセスではありません。systemd タイマーが5分おきに Python を起動し、1回の実行が終わるとプロセスは終了します。

```
mc-monitor.timer（5分ごと）
   ▼
mc-monitor.service（Type=oneshot）
   ▼
python3 monitor.py 実行 → 終了
```

1GB メモリの AMD Micro でも負担になりません。`systemctl status mc-monitor.service` が `inactive (dead)` なのは正常です。

## 実行間隔の変更

`/etc/systemd/system/mc-monitor.timer` の以下を編集します。

```ini
[Timer]
OnBootSec=5min          # 起動から初回実行までの待ち時間
OnUnitActiveSec=5min    # 前回実行から次回までの間隔
```

```bash
sudo systemctl daemon-reload
sudo systemctl restart mc-monitor.timer
```

`daemon-reload` をしないと古い設定のまま動き続けます。

## チェックリスト

```
[ ] FILESYSTEM_NAME を実測値に修正
[ ] monitor.py 配置
[ ] 強制発火テスト（Discord着弾確認）
[ ] カスタムメトリクス送信確認
[ ] タイマー有効化
```