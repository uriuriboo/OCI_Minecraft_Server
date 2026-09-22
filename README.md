# OCI Minecraft Server

Oracle Cloud Infrastructure の Always Free 枠で Minecraft (PaperMC) サーバーを運用する構成です。**インターネットに受信ポートを一切開けず**、月額 0 円で動きます。

```text
                    [インターネット]
                          │ すべてアウトバウンド接続のみ
                          ▼
        ┌─────────────────┴─────────────────┐
  [Tailscale]                        [playit.gg]
   SSH/管理                           Minecraft接続
        └─────────────────┬─────────────────┘
                          ▼
┌───────────────────────────────────────────────┐
│  OCI VCN 10.0.0.0/16                          │
│  ┌──────────────────────┐  ┌────────────────┐ │
│  │ mc-server (Arm)      │  │ mc-monitor     │ │
│  │ 2 OCPU / 12GB        │◄─┤ AMD Micro 1GB  │ │
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
| Minecraft の公開 | playit.gg / Tailscale / ZeroTier を切替。どれも受信ポートを開けない |
| 管理 SSH | Tailscale SSH。公開方式に関わらず共通 |
| 監視 | 別VM から RCON + OCI Monitoring。Discord へ通知 |
| バックアップ | R2 + OCI Object Storage の二重化 (手動実行) |
| 構成管理 | Terraform + cloud-init が主体。Ansible は稼働後の更新のみ |

## クイックスタート

Terraform は [tenv](https://github.com/tofuutils/tenv)、Python は [uv](https://docs.astral.sh/uv/) で管理します。

```bash
# ツール導入 (詳細は docs/spec/A2-toolchain.md)
scoop install tenv uv        # Windows
brew install tenv uv         # macOS

cd terraform
tenv tf install                               # .terraform-version の版を入れる
cp terraform.tfvars_sample terraform.tfvars   # 値を埋める
terraform init
terraform apply
```

**これだけでサーバーが起動します。** 必要な値の入手元は [docs/spec/08-parameters.md](docs/spec/08-parameters.md)、取得手順は [docs/manual/01-prerequisites.md](docs/manual/01-prerequisites.md) にあります。

構築後の確認は [docs/spec/09-verification.md](docs/spec/09-verification.md) の受入試験を上から順に実施してください。

> **構築前に知っておくこと**
>
> 1. **Tailscale の疎通確認は SSH 穴を閉じる前に行う** — 逆にするとどこからも入れなくなります
> 2. **`terraform plan` に `must be replaced` が出たら apply しない** — VM の置換はワールドの消失を意味します
> 3. **バックアップは構築直後に一度復元してみる** — 復元できて初めて機能します

## ドキュメント

目的の違う3種類があります。

| | 答える問い | 場所 |
| --- | --- | --- |
| **仕様書** | 何を作るのか、なぜそうするのか | [docs/spec/](docs/spec/) |
| **手順書** | どう作業するのか | [docs/manual/](docs/manual/) (構築時の記録。実装との不整合は修正済み) |
| **wiki** | 上記を GitHub wiki で公開したもの | [docs/wiki/](docs/wiki/) (`docs/spec/` から生成) |

食い違う場合は**仕様書を正**とします。差分の全件と判断理由は [docs/spec/A1-doc-reconciliation.md](docs/spec/A1-doc-reconciliation.md) にあります。

| 目的 | 参照 |
| --- | --- |
| 手元にツールを入れる | [docs/spec/A2-toolchain.md](docs/spec/A2-toolchain.md) |
| 構成を理解したい | [docs/spec/02-architecture.md](docs/spec/02-architecture.md) |
| 設定を変えたい | [docs/spec/06-operations.md](docs/spec/06-operations.md) の変更管理 |
| 障害対応中 | [docs/spec/06-operations.md](docs/spec/06-operations.md) の障害対応 |
| どの値をどこに入れるか | [docs/spec/08-parameters.md](docs/spec/08-parameters.md) |
| バージョンを上げたい | [docs/spec/07-tech-stack.md](docs/spec/07-tech-stack.md) |

## ディレクトリ構成

```text
minecraft_oci/
├── terraform/          構成の主体
│   ├── *.tf                インフラ定義
│   ├── templates/          compose / .env / backup.sh の唯一の正
│   ├── cloud-init/         初回構築の全て
│   └── terraform.tfvars_sample
├── ansible/            稼働後の更新のみ (site.yml 1本)
├── monitor/            monitor.py と systemd unit (唯一の正)
├── env/                .env の参照用サンプル
├── tailscale/          ACL ポリシー
├── dashboards/         OCI ダッシュボードのウィジェット定義
├── scripts/            検証・生成・運用の補助
├── pyproject.toml      Python の依存定義 (uv)
│
└── docs/
    ├── spec/               仕様書
    ├── manual/             手順書 (構築時の記録。実装との不整合は修正済み)
    └── wiki/               GitHub wiki 用 (docs/spec/ から生成)
```

### Terraform と Ansible の役割分担

判断基準は **「VM を作り直さずに変更したいか」** の一点です。OCI は `metadata.user_data` の変更でインスタンスを置換し、それはブートボリュームの破棄 = **ワールド消失**を意味します。

| | 担当 |
| --- | --- |
| 初回構築で確定し、以後変わらないもの | **Terraform + cloud-init** |
| 稼働後に繰り返し変えるもの (compose / .env / monitor.py) | **Ansible** (`site.yml` の `app` / `monitor` タグ) |

`terraform apply` の時点で後者も cloud-init 経由で配置されるため、**Ansible を一度も実行しなくてもサーバーは動きます**。詳細は [docs/spec/02-architecture.md](docs/spec/02-architecture.md)。

同じ `docker-compose.yml` を2箇所で管理しないため、Terraform のテンプレートを唯一の正とし、レンダリング結果を `local_file` で `ansible/files/` に書き出しています。Ansible は Jinja2 テンプレートを持たず、成果物を配送するだけです。

## よく使うコマンド

```bash
# 変更を適用
cd terraform && terraform apply                       # インフラ + ansible/files/ を更新
cd ansible  && ansible-playbook site.yml -t app       # compose / .env を配送
cd ansible  && ansible-playbook site.yml -t monitor   # monitor.py / .env を配送

# 検証 (クラウド不要)
cd terraform && terraform validate
uv run scripts/check-consistency.py                   # 設定の整合性
uv run scripts/sync-wiki.py --check                   # wiki の同期漏れ

# 運用
uv run scripts/print-dashboard.py                     # ダッシュボード用 MQL
ssh ubuntu@mc-server '~/minecraft/backup.sh'          # バックアップ
./scripts/deploy-monitor.sh                           # Ansible なしで monitor 更新

# monitor.py の依存を変えたとき
uv pip compile pyproject.toml --group monitor --python-version 3.12 --python-platform x86_64-unknown-linux-gnu -o monitor/requirements.txt
```

VS Code では `Ctrl+Shift+P` → Tasks: Run Task から同じものを実行できます ([.vscode/tasks.json](.vscode/tasks.json))。

Ansible は Windows をコントロールノードにできないため、WSL2 または mc-monitor 上から実行してください ([ansible/README.md](ansible/README.md))。

## 秘密情報

リポジトリには含めません。`*_sample` をコピーして埋めます。

| 実ファイル | サンプル |
| --- | --- |
| `terraform/terraform.tfvars` | [terraform/terraform.tfvars_sample](terraform/terraform.tfvars_sample) |
| `ansible/inventory.yml` | [ansible/inventory_sample.yml](ansible/inventory_sample.yml) |
| VM 上の `.env` (Terraform が生成) | [env/](env/) 配下の `*_sample` (参照用) |

`scripts/check-consistency.py` が `.gitignore` の取りこぼしを検査します。
