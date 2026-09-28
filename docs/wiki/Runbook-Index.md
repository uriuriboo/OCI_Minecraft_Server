# 手順書の一覧

構築作業の手順書は `docs/manual/` にあります。**この wiki には転記せず**、リポジトリ上の原本にリンクします。二重管理を避けるためです。

手順書は構築時の記録として保存していますが、実装と食い違いが見つかれば直接修正しています。それでも記述が食い違う場合は**仕様書を正**としてください。修正内容と判断理由は [A1. 手順書との差分](Spec-A1-doc-reconciliation) にあります。

## 構築の流れ

| 手順書 | 内容 | 対応する仕様書 |
| --- | --- | --- |
| [00-overview.md](../blob/main/docs/manual/00-overview.md) | 構成概要 | [02. アーキテクチャ](Spec-02-architecture) |
| [01-prerequisites.md](../blob/main/docs/manual/01-prerequisites.md) | 事前準備 (OCI CLI、鍵、各種アカウント) | [08. パラメータ](Spec-08-parameters) |
| [02-post-setup.md](../blob/main/docs/manual/02-post-setup.md) | 構築後の手動作業 | [09. 検証方法](Spec-09-verification) |
| [02b-tailscale-acl.md](../blob/main/docs/manual/02b-tailscale-acl.md) | Tailscale ACL 設定 | [03. ネットワーク・セキュリティ](Spec-03-network-security) |
| [03-monitoring.md](../blob/main/docs/manual/03-monitoring.md) | monitor.py と通知設定 | [04. 監視](Spec-04-monitoring) |
| [04-dashboard.md](../blob/main/docs/manual/04-dashboard.md) | OCI Dashboards 設定 | [04. 監視](Spec-04-monitoring) |
| [05-backup.md](../blob/main/docs/manual/05-backup.md) | バックアップ運用 | [05. バックアップ](Spec-05-backup) |
| [06-operations.md](../blob/main/docs/manual/06-operations.md) | 運用・トラブルシュート | [06. 運用・保守](Spec-06-operations) |
| [07-exposure-options.md](../blob/main/docs/manual/07-exposure-options.md) | 公開方式の選択と設定 | [02. アーキテクチャ](Spec-02-architecture) |
| [08-server-management.md](../blob/main/docs/manual/08-server-management.md) | 荒らし対策と権限管理 | [03. ネットワーク・セキュリティ](Spec-03-network-security) |

## 手順書を読むときの注意

Terraform コードを載せていた `02-terraform.md` は**削除済み**です (章番号 02 が欠けているのはそのため)。**実行可能な正は [terraform/](../blob/main/terraform) ディレクトリのコード**で、設計の説明は [02. アーキテクチャ](Spec-02-architecture)、変数の一覧は [08. パラメータ](Spec-08-parameters) にあります。旧ドラフトには以下が残っていました。

- `# (既存の内容のまま)` のプレースホルダ (実体は復元済み)
- 動かないコード (`oci_identity_tenancy` の参照先など)
- 1つの公開方式に固定された cloud-init

いずれも [A1. 手順書との差分](Spec-A1-doc-reconciliation) に列挙し、コード側で修正しています。

## 実際の作業で使うもの

構築・運用の実務では、手順書よりこちらを使ってください。

| やること | 参照 |
| --- | --- |
| 構築 | [09. 検証方法](Spec-09-verification) の受入試験を上から順に |
| 日々の運用コマンド | [06. 運用・保守](Spec-06-operations) |
| 設定変更 | [06. 運用・保守](Spec-06-operations) の変更管理 |
| 障害対応 | [06. 運用・保守](Spec-06-operations) の障害対応 |
| バージョン更新 | [07. 構成技術・バージョン](Spec-07-tech-stack) |
