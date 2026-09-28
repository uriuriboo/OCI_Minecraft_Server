# OCI Minecraft Server

Oracle Cloud Infrastructure の Always Free 枠で Minecraft (PaperMC) サーバーを運用するための構成です。

**インターネットに受信ポートを一切開けず**、月額 0 円で動きます。

## 構成の要点

```text
                    [インターネット]
                          │
                          │ すべてアウトバウンド接続のみ
                          │ (受信ポートの開放なし)
                          ▼
        ┌─────────────────┴─────────────────┐
  [Tailscale]                        [playit.gg]
   SSH/管理                           Minecraft接続
        │                                   │
        └─────────────────┬─────────────────┘
                          ▼
┌───────────────────────────────────────────────┐
│  OCI VCN                                      │
│  ┌──────────────────────┐  ┌────────────────┐ │
│  │ mc-server (Arm)      │  │ mc-monitor     │ │
│  │ 2 OCPU / 12GB        │◄─┤ AMD Micro      │ │
│  │ PaperMC (Docker)     │  │ monitor.py     │ │
│  └──────────────────────┘  └────────────────┘ │
│         RCON 25575 ◄─────────────┘            │
└───────────────────────────────────────────────┘
        │              │               │
        ▼              ▼               ▼
  [Cloudflare R2]  [OCI Object    [OCI Monitoring]
                    Storage]      → Dashboards / Discord
```

| 項目 | 選択 |
| --- | --- |
| Minecraft の公開 | playit.gg / Tailscale / ZeroTier を切替 (どれも受信ポートを開けない) |
| 管理 SSH | Tailscale SSH (公開方式に関わらず共通) |
| 監視 | 別VM から RCON + OCI Monitoring。Discord へ通知 |
| バックアップ | R2 + OCI Object Storage の二重化 (手動実行) |
| 構成管理 | Terraform + cloud-init が主体。Ansible は稼働後の更新のみ |

## 読み方

このリポジトリには目的の違う2種類の文書があります。

| | 答える問い | 場所 |
| --- | --- | --- |
| **仕様書** | 何を作るのか、なぜそうするのか | この wiki (左サイドバー) |
| **手順書** | どう作業するのか | [手順書の一覧](Runbook-Index) |

食い違う場合は**仕様書を正**とします。差分の一覧と判断理由は [A1. 手順書との差分](Spec-A1-doc-reconciliation) にあります。

## はじめに読むもの

| 目的 | ページ |
| --- | --- |
| 何のための構成か知りたい | [00. 概要](Spec-00-introduction) |
| 構成を理解したい | [02. アーキテクチャ](Spec-02-architecture) |
| これから構築する | [09. 検証方法](Spec-09-verification) の受入試験を上から |
| 設定を変えたい | [06. 運用・保守](Spec-06-operations) の変更管理 |
| 障害対応中 | [06. 運用・保守](Spec-06-operations) の障害対応 |
| どの値をどこに入れるか知りたい | [08. パラメータ](Spec-08-parameters) |

## クイックスタート

```bash
cd terraform
cp terraform.tfvars_sample terraform.tfvars   # 値を埋める
terraform init
terraform apply
```

これだけでサーバーが起動します。必要な値の取得手順は [01. 要件](Spec-01-requirements) と手順書の事前準備にあります。

## 最初に押さえておくべき3点

構築前に知らないと事故になるものです。

1. **Tailscale の疎通確認は SSH 穴を閉じる前に行う** — 逆にするとどこからも入れなくなります ([03. ネットワーク・セキュリティ](Spec-03-network-security))
2. **`terraform plan` に `must be replaced` が出たら apply しない** — VM の置換はワールドの消失を意味します ([02. アーキテクチャ](Spec-02-architecture))
3. **バックアップは構築直後に一度復元してみる** — 復元できて初めて機能します ([05. バックアップ](Spec-05-backup))
