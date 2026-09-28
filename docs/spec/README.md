# 仕様書

Oracle Cloud Infrastructure 上に Minecraft (PaperMC) サーバーを構築・運用するための仕様書です。

## このディレクトリの位置づけ

このリポジトリには目的の違う2種類の文書があります。

| | 場所 | 答える問い | 読むとき |
| --- | --- | --- | --- |
| **仕様書** | `docs/spec/` | 何を作るのか、なぜそうするのか | 設計を把握したい / 変更の影響を知りたい |
| **手順書** | `docs/manual/` | どう作業するのか | 実際に手を動かすとき |

手順書 (`docs/manual/`) は構築作業の記録として保存していますが、実装と食い違いが見つかれば直接修正します。仕様書と手順書で記述が食い違う場合は**仕様書を正**とし、修正内容と判断理由を [A1-doc-reconciliation.md](A1-doc-reconciliation.md) に記録しています。

## 目次

| 章 | 内容 |
| --- | --- |
| [00-introduction.md](00-introduction.md) | 目的・スコープ・用語 |
| [01-requirements.md](01-requirements.md) | 機能要件・非機能要件・制約 |
| [02-architecture.md](02-architecture.md) | 全体構成、コンポーネントの責務、公開方式の選定 |
| [03-network-security.md](03-network-security.md) | ネットワーク設計とセキュリティ設計 |
| [04-monitoring.md](04-monitoring.md) | 監視・通知・可視化の設計 |
| [05-backup.md](05-backup.md) | バックアップと復元の設計 |
| [06-operations.md](06-operations.md) | 運用・保守設計、変更管理 |
| [07-tech-stack.md](07-tech-stack.md) | 構成技術一覧とバージョン管理対象 |
| [08-parameters.md](08-parameters.md) | 全パラメータ一覧 |
| [09-verification.md](09-verification.md) | 検証方法と受入試験項目 |
| [10-ownership.md](10-ownership.md) | 担当者・体制 |
| [A1-doc-reconciliation.md](A1-doc-reconciliation.md) | 手順書との差分記録 |
| [A2-toolchain.md](A2-toolchain.md) | 管理端末のツール導入 (tenv / uv) |

## リポジトリ構成

```text
minecraft_oci/
├── docs/
│   ├── spec/        この仕様書
│   ├── manual/      手順書 (原本、無変更)
│   └── wiki/        GitHub wiki 用 (docs/spec/ から生成)
│
├── terraform/       構成の主体。インフラ + cloud-init + テンプレート
├── ansible/         稼働後の更新のみ (最小限)
├── monitor/         monitor.py と systemd unit (唯一の正)
├── env/             .env の参照用サンプル
├── tailscale/       ACL ポリシー
├── dashboards/      OCI ダッシュボードのウィジェット定義
└── scripts/         補助スクリプト
```

## クイックスタート

ツールの導入は [A2-toolchain.md](A2-toolchain.md) を参照してください (Terraform は tenv、Python は uv で管理します)。

```bash
cd terraform
tenv tf install                               # .terraform-version の版を入れる
cp terraform.tfvars_sample terraform.tfvars   # 値を埋める
terraform init
terraform apply
```

これだけでサーバーが起動します。詳細は [09-verification.md](09-verification.md) の受入試験項目に沿って確認してください。
