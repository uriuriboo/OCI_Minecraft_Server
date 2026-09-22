# 05. OCI Dashboards

保存先: `docs/05-dashboard.md`

## 表示できるもの

### 標準メトリクス（追加実装なし）

Oracle Cloud Agent が自動収集しているため、monitor.py に関係なく表示できます。

| ネームスペース | メトリック | 内容 |
|---|---|---|
| `oci_computeagent` | `CpuUtilization` | CPU使用率 |
| `oci_computeagent` | `MemoryUtilization` | メモリ使用率 |
| `oci_computeagent` | `FilesystemUtilization` | ディスク使用率（ワールド肥大化の把握） |
| `oci_computeagent` | `DiskBytesRead` / `DiskBytesWritten` | ディスクI/O（バックアップ時の負荷） |
| `oci_computeagent` | `NetworksBytesIn` / `NetworksBytesOut` | 通信量（プレイヤーの出入り） |
| `oci_computeagent` | `LoadAverage` | システム負荷平均 |

mc-server と mc-monitor の両方を個別に取得できるので、比較表示も可能です。

### カスタムメトリクス（monitor.py が送信）

| ネームスペース | メトリック | 内容 |
|---|---|---|
| `custom_minecraft` | `TPS` | サーバー処理速度の推移 |
| `custom_minecraft` | `PlayerCount` | 時間帯別のプレイヤー数 |
| `custom_minecraft` | `ServerOnline` | 死活状態（1/0） |

### 表示できないもの

- Minecraft のゲームログ内容 → Logging サービスが別途必要
- バックアップの成否履歴 → カスタムメトリクスを追加すれば可能
- Tailscale の接続状態 → Tailscale 管理画面で確認

## ダッシュボード作成

コンソール → 監視 → ダッシュボード → 「ダッシュボードの作成」

### 推奨ウィジェット構成

| ウィジェット | ネームスペース | メトリック | 形式 |
|---|---|---|---|
| CPU使用率 | `oci_computeagent` | `CpuUtilization` | 折れ線（2台比較） |
| メモリ使用率 | `oci_computeagent` | `MemoryUtilization` | 折れ線 |
| ディスク使用率 | `oci_computeagent` | `FilesystemUtilization` | 折れ線（トレンド） |
| TPS | `custom_minecraft` | `TPS` | 折れ線 |
| プレイヤー数 | `custom_minecraft` | `PlayerCount` | 棒グラフ |
| サーバー死活 | `custom_minecraft` | `ServerOnline` | 単一値 |

### MQL の書き方

各ウィジェットのメトリック・クエリ欄で指定します。

```
# CPU使用率（mc-server のみ）
CpuUtilization[5m]{resourceId = "ocid1.instance.oc1..xxxxx"}.mean()

# TPS
TPS[5m]{resourceName = "mc-server"}.mean()

# プレイヤー数
PlayerCount[5m]{resourceName = "mc-server"}.max()

# 死活状態
ServerOnline[5m]{resourceName = "mc-server"}.min()
```

## 画面イメージ

```
┌─────────────────────────────────────────┐
│ mc-server: CPU使用率（過去24時間）        │
├─────────────────────────────────────────┤
│ mc-server: メモリ使用率                   │
├─────────────────────────────────────────┤
│ mc-server: ディスク使用率（増加トレンド） │
├─────────────────────────────────────────┤
│ プレイヤー数                              │
├─────────────────────────────────────────┤
│ TPS                                      │
├─────────────────────────────────────────┤
│ mc-monitor: CPU/メモリ                   │
└─────────────────────────────────────────┘
```

TPS とプレイヤー数を並べると、「何人を超えるとTPSが落ちるか」の相関が目視できます。ディスク使用率のトレンドは、ワールド肥大化の早期発見に使えます。

## OCI 標準アラームの併用（任意）

Discord 通知は monitor.py が担っていますが、OCI 標準のアラームを併設すると **monitor.py 自体が落ちた場合の保険**になります。

コンソール → 監視 → アラーム定義 → 作成

```
メトリック名前空間: oci_computeagent
メトリック名: CpuUtilization
統計: mean
間隔: 5分
演算子: 以上
しきい値: 85
```

宛先は Notifications トピック経由です。Discord への直接連携はないため、Functions を挟む必要があります。Functions が Always Free 対象かは公式一覧で明記されていないため、**OCI 標準アラームはメール通知のみに留め、Discord は monitor.py に一本化**するのが確実です。

## 役割分担

| 機能 | 役割 |
|---|---|
| monitor.py | 能動的なDiscord通知 |
| monitor.py（送信部） | カスタムメトリクスの書き込み |
| Console Dashboards | 標準+カスタムを1画面で可視化 |
| OCI標準アラーム（任意） | monitor.py 死亡時の保険、メールのみ |

## チェックリスト

```
[ ] ダッシュボード作成
[ ] 標準メトリクスのウィジェット配置
[ ] カスタムメトリクスのウィジェット配置
[ ] （任意）OCI標準アラーム設定
```