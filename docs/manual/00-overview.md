# 00. 構成概要

## 全体像

```
                    [インターネット]
                          │
                          │ すべてアウトバウンド接続のみ
                          │ (受信ポートの開放なし)
                          ▼
        ┌─────────────────┴─────────────────┐
        │                                   │
  [Tailscale]                        [playit.gg]
   SSH/管理 + 接続(方式B)              Minecraft接続(方式A)
        │                                   │
        └─────────────────┬─────────────────┘
                          ▼
┌───────────────────────────────────────────────┐
│  OCI VCN 10.0.0.0/16                          │
│  Public Subnet 10.0.1.0/24                    │
│                                               │
│  ┌──────────────────────┐  ┌────────────────┐ │
│  │ mc-server (Arm)      │  │ mc-monitor     │ │
│  │ 10.0.1.10            │◄─┤ 10.0.1.20      │ │
│  │ 2 OCPU / 12GB        │  │ AMD Micro      │ │
│  │                      │  │ 1/8 OCPU / 1GB │ │
│  │ - PaperMC (Docker)   │  │                │ │
│  │ - Tailscale (SSH)    │  │ - monitor.py   │ │
│  │ - playit agent       │  │   (5分ごと)    │ │
│  │   ※方式Aの場合       │  │ - Tailscale    │ │
│  │ - rclone (手動)      │  │                │ │
│  └──────────────────────┘  └────────────────┘ │
│         RCON 25575 ◄─────────────┘            │
└───────────────────────────────────────────────┘
        │                              │
        ▼                              ▼
  [Cloudflare R2]              [OCI Monitoring]
                                  │        │
                          [Dashboards]  [Discord]
```

## 設計方針

| 項目 | 選択 | 理由 |
|---|---|---|
| Minecraft公開 | playit.gg **または** Tailscale/ZeroTier | どちらも受信ポートを開けない（`07-exposure-options.md` 参照） |
| SSH | Tailscale SSH | 公開方式に関わらず共通。自宅IPの変動に影響されない |
| RCON | VCN内プライベートIP | Tailscaleを経由せず閉域で完結 |
| 監視 | 別VM (mc-monitor) | サーバーごと落ちた時も検知できる |
| メトリクス | OCI Monitoring | VictoriaMetrics常駐が不要 |
| 通知 | 監視VMから直接Discord | Functions無料枠の不確実性を回避 |
| 可視化 | OCI Console Dashboards | 標準機能で完結 |
| バックアップ | 手動 `docker run --rm` | 常駐プロセスゼロ |

## ドキュメント構成

| ファイル | 内容 |
|---|---|
| `00-overview.md` | この文書 |
| `01-prerequisites.md` | 事前準備(手動) |
| `02-post-setup.md` | 構築後の手動作業 |
| `02b-tailscale-acl.md` | Tailscale ACL 設定 |
| `03-monitoring.md` | monitor.py と通知設定 |
| `04-dashboard.md` | OCI Dashboards 設定 |
| `05-backup.md` | バックアップ運用 |
| `06-operations.md` | 運用・トラブルシュート |
| `07-exposure-options.md` | 公開方式の選択と設定 |
| `08-server-management.md` | 荒らし対策と権限管理 |

Terraform コード一式は手順書に持たない。正は [terraform/](../../terraform/) のコードで、設計の説明は [docs/spec/02-architecture.md](../spec/02-architecture.md)、変数の一覧は [docs/spec/08-parameters.md](../spec/08-parameters.md) にある。
