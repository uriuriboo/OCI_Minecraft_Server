# 07. 構成技術一覧とバージョン管理

## 構成技術一覧

### クラウド

| 技術 | 用途 | Always Free 枠 |
| --- | --- | --- |
| OCI Compute (VM.Standard.A1.Flex) | mc-server | Arm 無料枠 2 OCPU / 12GB を全量使用（2026-06-15 に 4 OCPU / 24GB から半減） |
| OCI Compute (VM.Standard.E2.1.Micro) | mc-monitor | 2台まで無料 |
| OCI Block Volume | ブートボリューム 100GB + 50GB | 合計 200GB まで無料 |
| OCI VCN / NSG / Internet Gateway | ネットワーク | 無料 |
| OCI Monitoring | メトリクスの保管とクエリ | 無料 |
| OCI Console Dashboards | 可視化 | 無料 |
| OCI Object Storage | バックアップの二次コピー | 20GB まで無料 |
| OCI IAM (動的グループ / ポリシー) | インスタンスプリンシパル | 無料 |
| Cloudflare R2 | バックアップの一次コピー | 10GB / 月100万リクエスト |

### 使っていない OCI サービス

`todo.md` で検討していたもののうち、現時点で採用していないサービスと理由。

| サービス | 採用しない理由 | 導入を検討する条件 |
| --- | --- | --- |
| OCI Resource Manager | 単独運用なら state はローカルで足りる | 複数人で管理するようになったら |
| OCI Logging | ゲームログの検索が現状不要 | 荒らしの調査が必要になったら |
| OCI Vault | tfvars で足りている | 秘密を管理端末から出したくなったら |
| OCI Bastion | Tailscale SSH で足りている。シリアルコンソールも残っている | - |
| OCI Certificates | HTTPS を終端する要素がない | Web UI を公開するようになったら |
| OCI Functions | **Always Free 対象か公式一覧に明記されていない** | 明記されたら Discord 連携に使える |
| OCI Notifications | Discord 連携がない。メール通知の保険としてのみ | 標準アラームを併設するとき |

### ソフトウェア

| 技術 | バージョン指定 | 用途 |
| --- | --- | --- |
| Ubuntu | 24.04 (最新イメージを data source で取得) | 両VMのOS |
| Docker (docker.io) | Ubuntu のリポジトリ版 | コンテナ実行 |
| Docker Compose v2 (docker-compose-v2) | Ubuntu のリポジトリ版 | コンテナ管理 |
| PaperMC (`itzg/minecraft-server`) | `TYPE=PAPER` / `VERSION=LATEST` | Minecraft 本体 |
| `itzg/mc-router` | latest | playit からの接続の中継と接続レート制限 (`exposure_mode=playit` のみ) |
| `itzg/mc-backup` | latest | バックアップ |
| playit-agent (`ghcr.io/playit-cloud/playit-agent`) | **1.0 (固定)** | トンネル (`exposure_mode=playit`) |
| Tailscale | 公式 install.sh (最新) | SSH + オーバーレイ |
| ZeroTier | 公式 install スクリプト (最新) | オーバーレイ (任意) |
| rclone | Ubuntu のリポジトリ版 | R2 への転送 |
| uv | 公式 install.sh (`/usr/local/bin`) | Python 環境と依存の管理 (両VM) |
| OCI CLI | `uv tool install oci-cli` | OCI Object Storage への転送 (mc-server) |
| iptables-persistent | Ubuntu のリポジトリ版 | iptables の永続化 |
| unattended-upgrades | Ubuntu のリポジトリ版 | OS 自動更新 |

`python3-pip` と `python3-venv` は**入れていない**。uv が venv の作成を自前で行い `ensurepip` を必要としないためである。1/8 OCPU の Micro VM では pip の依存解決が cloud-init のタイムアウトに近づくため、速度面でも uv が有利である。

### 構成管理・開発

| 技術 | バージョン指定 | 用途 |
| --- | --- | --- |
| tenv | 最新 | Terraform のバージョン管理 |
| Terraform | `~> 1.9` / `.terraform-version` で `1.16.3` に固定 | インフラ + テンプレートのレンダリング |
| oracle/oci provider | `~> 9.0` → `.terraform.lock.hcl` で固定 | OCI リソース |
| hashicorp/local provider | `~> 2.5` → 同上 | `ansible/files/` への書き出し |
| uv | 最新 | Python の実行と依存管理 |
| Python | `>= 3.11` (`pyproject.toml`) | monitor.py と補助スクリプト |
| Ansible (ansible-core) | `>= 2.16` | day-2 更新のみ |

固定の仕組みは3層になっている。

| 層 | ファイル | 効果 |
| --- | --- | --- |
| Terraform 本体 | `terraform/.terraform-version` | tenv が読み、端末を変えても同じ版が使われる |
| プロバイダ | `terraform/.terraform.lock.hcl` | `terraform init` が同じ版を選ぶ (コミットする) |
| Python 依存 | `monitor/requirements.txt` | 推移的依存まで全てピン留め (`uv pip compile` の生成物) |

Terraform 1.9 以上が必要なのは、`variables.tf` で**変数をまたぐ validation** を使っているためである (`enable_home_ssh = true` なのに `home_ip_cidr` が空なら弾く)。これは 1.9 で入った機能である。

導入手順は [A2. ツール導入](A2-toolchain.md)。

### Minecraft プラグイン

| プラグイン | SpigotMC ID | 用途 |
| --- | --- | --- |
| CoreProtect | 8631 | ブロック変更のログとロールバック |
| LuckPerms | 28140 | 段階的な権限管理 |

`mc_plugins` 変数で管理する (`SPIGET_RESOURCES`)。

### Python 依存 (monitor.py)

直接依存は `pyproject.toml` の `[dependency-groups] monitor` に宣言する。

| パッケージ | 制約 | 用途 |
| --- | --- | --- |
| `oci` | `>=2.126,<3` | Monitoring API |
| `requests` | `>=2.32,<3` | Discord Webhook |
| `mcrcon` | `>=0.7,<1` | RCON |
| `python-dotenv` | `>=1,<2` | `.env` の読み込み |

VM に配る `monitor/requirements.txt` は**そこから生成する**。推移的依存まで全てピン留めされるため、無人稼働のサーバーで予期しない破壊的変更を拾わない。

```bash
uv pip compile pyproject.toml --group monitor --python-version 3.12 --python-platform x86_64-unknown-linux-gnu -o monitor/requirements.txt
```

VM 側が `pyproject.toml` ではなく `requirements.txt` を読むのは、リポジトリ全体を持ち込まずに1ファイルだけ配送すれば済むようにするためである。VM 上では `uv pip sync` で適用するので、requirements.txt から消したパッケージは環境からも消える。

**`requirements.txt` を手で編集しないこと。** 変更は `pyproject.toml` に入れて再生成する。

## バージョン更新対象一覧

更新の必要があるものを、確認方法と更新手順とともに列挙する。

### 固定していて明示的に上げる必要があるもの

| 対象 | 現在 | 定義場所 | 確認方法 | 更新手順 |
| --- | --- | --- | --- | --- |
| Terraform | `1.16.3` | `terraform/.terraform-version` | [releases.hashicorp.com](https://releases.hashicorp.com/terraform/) | ファイルを書き換えて `tenv tf install` → `terraform validate` |
| Terraform の下限 | `~> 1.9` | `terraform/versions.tf` | - | 通常は変えない (1.9 の機能に依存している) |
| oracle/oci provider | `~> 9.0` | `terraform/versions.tf` | Terraform Registry | `terraform init -upgrade` → `terraform plan` で差分確認 → lock をコミット |
| hashicorp/local provider | `~> 2.5` | 同上 | 同上 | 同上 |
| tenv | 最新 | - | `tenv --version` | `scoop update tenv` / `brew upgrade tenv` |
| uv | 最新 | - | `uv --version` | `scoop update uv` / `uv self update` |
| ansible-core | `>= 2.16` | この表 | `ansible --version` | `apt upgrade ansible-core` (WSL2) |
| playit-agent | **1.0** | `terraform/templates/docker-compose.yml.tftpl` | [GitHub Releases](https://github.com/playit-cloud/playit-agent/releases) | タグを上げる前に `docker/entrypoint.sh` を確認 (`SECRET_KEY` の変数名が変わる可能性がある) → タグを上げて `terraform apply` → Ansible `-t app` |
| Python の直接依存 | `pyproject.toml` の制約 | `pyproject.toml` | PyPI | 制約を上げて `uv pip compile` → Ansible `-t monitor` |
| Python の推移的依存 | ピン留め済み | `monitor/requirements.txt` (生成物) | - | `uv pip compile` で再生成 |
| CoreProtect | 8631 (ID固定) | `terraform.tfvars` の `mc_plugins` | SpigotMC | ID は変わらない。SPIGET が最新版を取得する |
| LuckPerms | 28140 (ID固定) | 同上 | 同上 | 同上 |

### 自動または最新追従するもの

| 対象 | 追従の仕組み | 注意点 |
| --- | --- | --- |
| Ubuntu パッケージ | `unattended-upgrades` が自動 | セキュリティ更新のみ。メジャーアップグレードはしない |
| Ubuntu イメージ | `data.oci_core_images` が最新を取得。ただし `ignore_changes` で既存VMには反映しない | VM 再作成時に新しいイメージになる |
| PaperMC | `VERSION=LATEST`。コンテナ再作成時に取得 | **Minecraft のメジャーバージョンが上がるとプラグイン互換が壊れる可能性がある。更新前にバックアップを取る** |
| `itzg/minecraft-server` | `latest`。`docker compose pull` で取得 | 同上 |
| `itzg/mc-router` | `latest` | 更新後は playit 経由で実際に接続して経路を確認する |
| `itzg/mc-backup` | `latest` | バックアップ形式が変わる可能性は低い |
| Tailscale | `install.sh` が最新を入れる。以後は apt で更新 | - |
| ZeroTier | 同様 | - |
| uv (VM 上) | `install.sh` が最新を入れる。以後は固定 | `uv self update` |
| OCI CLI (VM 上) | uv tool。明示的に更新しない限り固定 | `env UV_TOOL_DIR=/opt/uv-tools uv tool upgrade oci-cli` |

### 更新前にバックアップが必須なもの

| 対象 | 理由 |
| --- | --- |
| PaperMC / Minecraft のバージョン | ワールドフォーマットが変わると戻せない |
| プラグインのメジャー更新 | 設定ファイルの互換性 |
| VM の再作成 (`-replace`) | ブートボリュームが破棄される |

```bash
# 更新前に必ず
ssh ubuntu@mc-server '~/minecraft/backup.sh'
```

## Minecraft バージョンを固定したい場合

`VERSION=LATEST` は自動で最新を追うため、プラグイン互換が壊れることがある。固定したい場合は `terraform/templates/docker-compose.yml.tftpl` の `VERSION` を具体的なバージョンに変える。

```yaml
VERSION: "1.21.4"
```

変更後は `terraform apply` → Ansible `-t app` で反映する。この値を変数化していないのは、今のところ最新追従で問題が出ていないためである。必要になったら `mc_version` 変数として切り出す。
