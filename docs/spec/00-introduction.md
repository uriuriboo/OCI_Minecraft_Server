# 00. 概要

## 目的

友人内で遊ぶための Minecraft (PaperMC) サーバーを Oracle Cloud Infrastructure の Always Free 枠で運用する。以下を同時に満たすことを目的とする。

- **金銭的コストをゼロに保つ** — Always Free 枠を超えない
- **インターネットに攻撃面を出さない** — 受信ポートの開放をゼロにする
- **無人で動かす** — 常駐プロセスと定期的な手作業を最小化する
- **壊れても戻せる** — ワールドデータを別事業者にも保全する

## スコープ

### 対象

| 領域 | 内容 |
| --- | --- |
| インフラ | VCN / サブネット / NSG / Compute 2台 / Object Storage / IAM |
| サーバー | PaperMC (Docker)、プラグイン、ホワイトリスト、権限管理 |
| 公開 | playit.gg / Tailscale / ZeroTier の3方式 (切替可) |
| 管理アクセス | Tailscale SSH |
| 監視 | OCI Monitoring (標準 + カスタム)、Discord 通知、ダッシュボード |
| バックアップ | Cloudflare R2 + OCI Object Storage への二重化、復元 |
| 構成管理 | Terraform + cloud-init (主体)、Ansible (更新のみ) |

### 対象外

| 項目 | 理由 |
| --- | --- |
| 高可用性 (冗長化・自動フェイルオーバー) | 友人内の遊び用。停止しても事業影響がない |
| ゲームログの検索・集約 | OCI Logging が必要。運用して不便を感じたら導入する |
| バックアップの自動化 | 手動実行を前提とする ([05-backup.md](05-backup.md) 参照) |
| Terraform state のリモート管理 | 単独運用のためローカルで足りる |
| Minecraft のワールド設計・ゲームプレイ | 技術基盤のみを扱う |

## 設計の基本方針

| 方針 | 具体化 |
| --- | --- |
| 受信ポートを開けない | すべてアウトバウンド接続を使い回す。NSG に 25565 の ingress を作らない |
| 常駐プロセスを増やさない | 監視は systemd タイマーの oneshot、バックアップは使い捨てコンテナ |
| 抽象化は必要になってから足す | 最初から Ansible / Logging / Resource Manager を全面導入しない |
| 単一の正を1箇所に置く | 同じ設定を2箇所で管理しない ([02-architecture.md](02-architecture.md) 参照) |
| 壊れる前提で作る | ワールド消失・SSH 不能・トンネル停止それぞれに退路を用意する |

## 用語

| 用語 | 意味 |
| --- | --- |
| **Always Free** | OCI の無期限無料枠。Arm 2 OCPU/12GB（2026-06-15 に 4 OCPU/24GB から半減）、AMD Micro 2台、Object Storage 20GB 等 |
| **mc-server** | Minecraft 本体を動かす Arm VM (2 OCPU / 12GB。Always Free の Arm 枠を全量使用) |
| **mc-monitor** | 監視専用の AMD Micro VM (1/8 OCPU / 1GB) |
| **exposure_mode** | Minecraft の公開方式。`playit` / `tailscale` / `zerotier` |
| **RCON** | Minecraft のリモートコンソールプロトコル。監視とバックアップが使う |
| **TPS** | Ticks Per Second。サーバーの処理速度。20 が上限 |
| **tailnet** | Tailscale が構成する仮想プライベートネットワーク |
| **MagicDNS** | Tailscale がホスト名を解決する機能。`mc-server` で名前引きできる |
| **インスタンスプリンシパル** | VM 自身を IAM の主体として扱う認証方式。VM 上に鍵を置かずに済む |
| **MQL** | Monitoring Query Language。OCI のメトリクス問い合わせ言語 |
| **cloud-init** | 初回起動時に OS を設定する仕組み。OCI では `user_data` で渡す |
| **day-2 作業** | 構築後に繰り返し発生する運用作業 |

## 関連文書

| 文書 | 内容 |
| --- | --- |
| [docs/manual/](../manual/) | 構築手順書 (原本) |
| [todo.md](../../todo.md) | 検討中の項目 |
