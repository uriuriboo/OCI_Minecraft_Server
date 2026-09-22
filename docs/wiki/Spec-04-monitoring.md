<!-- このページは docs/spec/04-monitoring.md から生成しています。直接編集しないでください。
     修正は docs/spec/ 側に入れて `python scripts/sync-wiki.py` を実行してください。 -->

# 04. 監視・通知・可視化

## 役割分担

```text
1. 読む
   ├─ RCON (mc-monitor → 10.0.1.10:25575) → TPS、プレイヤー数、死活
   └─ OCI Monitoring API                  → CPU、メモリ、ディスク

2. 判定する
   └─ 閾値と比較し、状態の変化を検出する

3. 書く
   ├─ Discord Webhook      → アラート通知
   └─ OCI Monitoring API   → TPS/プレイヤー数/死活を記録 (Dashboards用)
```

| 機能 | 担当 | 停止したときの影響 |
| --- | --- | --- |
| CPU / メモリ / ディスク / NW の収集 | Oracle Cloud Agent | メトリクスが途切れる。monitor.py とは独立 |
| TPS / プレイヤー数 / 死活の収集 | monitor.py | 該当メトリクスとDiscord通知だけが止まる |
| Discord 通知 | monitor.py | 通知が止まる。Minecraft は動き続ける |
| playit トンネルの死活 | playit-check.sh (mc-server) | トンネル停止が通知されなくなる |
| 可視化 | OCI Console Dashboards | - |
| monitor.py 自体の死活 | (任意) OCI 標準アラーム → メール | - |

**monitor.py は読むだけで、Minecraft の稼働に一切干渉しない。** 止まっても CPU・メモリ・ディスクのメトリクスは Cloud Agent が収集し続ける。

## 監視対象メトリクス

### 標準メトリクス (追加実装なし)

ネームスペース `oci_computeagent`。mc-server と mc-monitor の両方で取得できる。

| メトリック | 内容 | 用途 |
| --- | --- | --- |
| `CpuUtilization` | CPU使用率 | アラート + ダッシュボード |
| `MemoryUtilization` | メモリ使用率 | アラート + ダッシュボード |
| `FilesystemUtilization` | ディスク使用率 | アラート + ワールド肥大化の把握 |
| `DiskBytesRead` / `DiskBytesWritten` | ディスクI/O | バックアップ時の負荷 |
| `NetworksBytesIn` / `NetworksBytesOut` | 通信量 | プレイヤーの出入り |
| `LoadAverage` | システム負荷平均 | 補助 |

`FilesystemUtilization` には `fileSystemName` ディメンションがあり、**この値は実測でしか分からない**。`/` ではなく `/dev/sda1` のようなデバイス名のことがある。違っているとディスク使用率だけ取得できない。`filesystem_name` 変数として切り出し、構築後に確認して設定する (V-08)。

### カスタムメトリクス (monitor.py が送信)

ネームスペース `custom_minecraft`。ディメンションは `resourceId` (インスタンスOCID) と `resourceName` (`mc-server`)。

| メトリック | 内容 | 送信条件 |
| --- | --- | --- |
| `TPS` | サーバー処理速度 (20が上限) | RCON 成功かつパース成功時 |
| `PlayerCount` | オンライン人数 | RCON 成功かつパース成功時 |
| `ServerOnline` | 死活 (1 / 0) | 常に |

送信間隔は5分なので、ダッシュボード上でデータポイントが疎らに見えるのは正常である。

カスタムメトリクスの投稿には IAM の `use metrics` 権限が必要で、`read metrics` だけでは 401 になる。両方を `terraform/iam.tf` で付与している。

### 取得していないもの

| 項目 | 理由 / 代替 |
| --- | --- |
| Minecraft のゲームログ内容 | OCI Logging が別途必要。運用して必要になったら導入 |
| バックアップの成否履歴 | カスタムメトリクスを追加すれば可能。現状は実行時の標準出力で確認 |
| Tailscale / playit の接続状態 | 各サービスの管理画面。playit と mc-router の死活は playit-check.sh が見る |
| プレイヤーごとの詳細 | RCON の `list` で人数のみ取得 |

### `mc_router_auto_scale` を有効にした場合の制約

monitor.py は RCON に直結しているため、**mc コンテナが意図的に停止しているのか落ちたのかを区別できない**。`mc_router_auto_scale = true` にして無人時に mc を停止させると、その間ずっと `ServerOnline = 0` が記録され、Discord に「サーバーが停止しています」が届く。

既定は `false` で、この問題は起きない ([02. アーキテクチャ](Spec-02-architecture) の「scale to zero を既定で無効にしている理由」)。有効にする場合は、死活判定を RCON ではなく mc-router (`mc-router:25565`) への status ping に変える改修が先に必要になる ([06. 運用・保守](Spec-06-operations) の将来の拡張候補)。

## アラート設計

### 閾値

| 項目 | 閾値 | 方向 | 変数 |
| --- | --- | --- | --- |
| CPU使用率 | 85% | 以上で発火 | `monitor_thresholds.cpu` |
| メモリ使用率 | 85% | 以上で発火 | `monitor_thresholds.memory` |
| ディスク使用率 | 80% | 以上で発火 | `monitor_thresholds.disk` |
| TPS | 15.0 | **未満**で発火 | `monitor_thresholds.tps` |
| RCON 応答 | - | 接続失敗で発火 | (固定) |

ディスクを 80% と他より厳しくしているのは、ワールドの肥大化が不可逆で、気づいてから対処するまでに時間が必要なためである。

### 状態変化のみ通知する

閾値を超え続けている間は毎回通知しない。**状態が変化した時だけ**送る。

```text
5分後: CPU 90% → 前回は正常 → 🚨 アラート送信
10分後: CPU 92% → 前回も異常 → 送信しない
15分後: CPU 50% → 前回は異常 → ✅ 復旧を送信
```

前回の判定結果は `/home/ubuntu/monitor_state.json` に保存する。常駐しないためファイルで持ち越す必要がある。

この設計により、5分間隔でも通知が溢れない。

### メトリクスが取得できなかった場合

取得できなかった項目は**前回の状態を保持する**。ここで状態をリセットすると、次回取得できた時に「初回超過」と誤認して再通知してしまう。

| 状況 | 挙動 |
| --- | --- |
| Monitoring API が失敗 | CPU/メモリ/ディスクの判定をスキップ。前回状態を維持 |
| RCON が失敗 | `ServerOnline = 0` を送信し、オフラインとして通知 |
| TPS のパース失敗 | TPS の判定のみスキップ |
| カスタムメトリクス送信が失敗 | 標準出力にログを出し、**Discord 通知は続行する** |

通知が最優先で、記録の失敗が通知を止めないようにしている。

### 通知の見た目

| 種別 | タイトル | 色 |
| --- | --- | --- |
| アラート | 🚨 アラート | `0xE74C3C` (赤) |
| 復旧 | ✅ 復旧 | `0x2ECC71` (緑) |

Discord の embed で送る。複数項目が同時に変化した場合は1通にまとめる。

## 実行方式

常駐プロセスではない。systemd タイマーが5分おきに Python を起動し、1回の実行が終わるとプロセスは終了する。

```text
mc-monitor.timer (OnUnitActiveSec=5min)
   ▼
mc-monitor.service (Type=oneshot)
   ▼
/home/ubuntu/venv/bin/python3 monitor.py → 終了
```

1GB メモリの AMD Micro でも負担にならない。`systemctl status mc-monitor.service` が `inactive (dead)` なのは**正常**である。

| 設定 | 値 | 意味 |
| --- | --- | --- |
| `OnBootSec` | 5min | 起動から初回実行まで。Cloud Agent のメトリクス反映待ちも兼ねる |
| `OnUnitActiveSec` | 5min | 前回実行から次回まで |
| `AccuracySec` | 30s | 起動タイミングの許容誤差 |

間隔を変えるときは `monitor/systemd/mc-monitor.timer` を編集して Ansible の `monitor` タグを適用する。`daemon-reload` をしないと古い設定のまま動き続けるため、Ansible 側で unit の変更を検出して `daemon-reload` → `restart` を実行している。

## 認証

monitor.py は**インスタンスプリンシパル**で OCI Monitoring API を呼ぶ。VM 上に APIキーを置かない。

```text
dg-monitor-instances (動的グループ: mc-monitor のみ)
  ├─ read metrics  … CPU/メモリ/ディスクの取得
  └─ use metrics   … カスタムメトリクスの投稿
```

401 が出る場合は `use metrics` が適用されているかを確認する。

インスタンスプリンシパルが使えない環境 (ローカル実行など) でも import 時に落ちないよう、クライアントは遅延生成している。この場合インフラメトリクスは取得できないが、RCON 監視と Discord 通知は動く。

## 可視化

### OCI Console Dashboards

ウィジェット定義は [dashboards/oci-dashboard.json](../blob/main/dashboards/oci-dashboard.json)。OCID を埋めた貼り付け用の MQL は次で生成できる。

```bash
python scripts/print-dashboard.py
```

| 段 | ウィジェット |
| --- | --- |
| 1 | サーバー死活 / プレイヤー数 / TPS (いずれも単一値) |
| 2 | 死活の推移 |
| 3 | プレイヤー数の推移 / TPS の推移 |
| 4 | CPU使用率 (2台比較) / メモリ使用率 |
| 5 | ディスク使用率 / ディスクI/O / 通信量 |

TPS とプレイヤー数を並べると「何人を超えると TPS が落ちるか」の相関が目視できる。ディスク使用率のトレンドはワールド肥大化の早期発見に使える。

更新間隔を5分より短くしても新しい点は増えない (monitor.py の送信間隔がそれだから)。

パネル構成は別リポジトリの Grafana 構成 (旧 `monitor_sample/`、削除済み) を参考にしている。対応は `oci-dashboard.json` の `grafana_equivalent` に記録している。OCI に state-timeline 相当のウィジェットがないため、死活の推移は折れ線で代用する (0 に落ちた区間が停止時間)。

### OCI 標準アラームの併用 (任意)

Discord 通知は monitor.py が担っているが、OCI 標準のアラームを併設すると **monitor.py 自体が落ちた場合の保険**になる。

```text
メトリック名前空間: oci_computeagent
メトリック名:      CpuUtilization
統計:              mean
間隔:              5分
演算子:            以上
しきい値:          85
```

宛先は Notifications トピック経由になる。Discord への直接連携はないため Functions を挟む必要があり、Functions が Always Free 対象かは公式一覧に明記されていない。したがって **OCI 標準アラームはメール通知のみに留め、Discord は monitor.py に一本化する**のが確実である。

## 将来の拡張

| やりたいこと | 方法 |
| --- | --- |
| バックアップの成否を記録したい | `backup.sh` からカスタムメトリクスを投稿する |
| ゲームログを検索したい | OCI Logging + Unified Monitoring Agent |
| プレイヤー数の急増を検知したい | 閾値監視に追加できるが、友人の一斉ログインで誤検知しやすい。ホワイトリストによる一次防御の方が確実 |
| 監視を OCI 外から行いたい | 自宅 Pi に monitor.py を移設。インスタンスプリンシパルが使えないため APIキー認証への変更が必要 |
