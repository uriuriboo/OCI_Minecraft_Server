# A2. 管理端末のツール導入

構築・運用を行う端末に必要なツールと、その導入方法。

VM 側のツールは cloud-init が入れるため、ここで扱うのは**手元の端末だけ**である。

## 一覧

| ツール | 必須 | 用途 | バージョン管理 |
| --- | --- | --- | --- |
| Terraform | ○ | インフラ構築、テンプレートのレンダリング | tenv + `terraform/.terraform-version` |
| uv | ○ | Python の実行と依存管理 | 自己更新 |
| Git | ○ | リポジトリ | - |
| OCI CLI | ○ | 初期設定と OCID の取得 | uv tool |
| ssh | ○ | VM への接続 | OS 同梱 |
| Ansible | △ | 稼働後の更新。WSL2 上に入れる | apt |
| Docker | ✕ | 検証で compose の妥当性を見るときだけ | - |

△ = なくても構築できる。`scripts/deploy-monitor.sh` で代替できる。

## Terraform (tenv 経由)

バージョンを直接入れるのではなく [tenv](https://github.com/tofuutils/tenv) で管理する。`terraform/.terraform-version` に固定したバージョンが自動で使われるため、**端末を変えても同じバージョンで動く**。

```powershell
# Windows (scoop)
scoop install tenv
```

```bash
# macOS (Homebrew)
brew install tenv
```

```bash
# Linux
# https://github.com/tofuutils/tenv/releases から取得、または
go install github.com/tofuutils/tenv/v4/cmd/tenv@latest
```

導入後、固定されたバージョンをインストールする。

```bash
cd terraform
tenv tf install          # .terraform-version を読んでその版を入れる
terraform -version       # 1.16.3 と表示される
```

`tenv` は `terraform` コマンドを自分のシムに差し替えるため、以後は `terraform` をそのまま使える。

### なぜ 1.9 以上が必要か

`terraform/variables.tf` で**変数をまたぐ validation** を使っている (`enable_home_ssh = true` なのに `home_ip_cidr` が空なら弾く)。これは Terraform 1.9 で入った機能である。

`versions.tf` の `required_version = "~> 1.9"` がこれを担保する。`.terraform-version` を下げると apply 時にエラーになる。

## uv

Python の実行環境と依存を [uv](https://docs.astral.sh/uv/) で管理する。

```powershell
# Windows (scoop)
scoop install uv
```

```bash
# macOS / Linux
curl -LsSf https://astral.sh/uv/install.sh | sh
```

### 手元での使い方

`scripts/` のスクリプトは標準ライブラリだけで動くので、依存のインストールは不要である。

```bash
uv run scripts/check-consistency.py
uv run scripts/sync-wiki.py
uv run scripts/print-dashboard.py
```

`python scripts/...` でも動く。`uv run` を使うと `requires-python = ">=3.11"` を満たす Python を自動で選ぶ。

### monitor.py の依存を変えるとき

直接依存は `pyproject.toml` の `[dependency-groups] monitor` に書く。VM へ配る `monitor/requirements.txt` は**そこから生成する**。

```bash
uv pip compile pyproject.toml --group monitor --python-version 3.12 --python-platform x86_64-unknown-linux-gnu -o monitor/requirements.txt
```

生成物は全ての推移的依存をピン留めしたものになる。VM 側が `pyproject.toml` ではなく `requirements.txt` を読むのは、リポジトリ全体を持ち込まずに1ファイルだけ配送すれば済むようにするためである。

反映は Ansible で行う。

```bash
cd ansible && ansible-playbook site.yml -t monitor
```

### VM 側でも uv を使っている

cloud-init が uv を `/usr/local/bin` に入れ、以下に使う。

| VM | 用途 |
| --- | --- |
| mc-monitor | `uv venv` で仮想環境作成、`uv pip sync` で依存を同期 |
| mc-server | `uv tool install oci-cli` でバックアップ用の OCI CLI |

`python3-pip` / `python3-venv` パッケージを入れていない。uv は venv の作成を自前で行い `ensurepip` を必要としないためである。1/8 OCPU の Micro VM では pip の依存解決が遅く cloud-init のタイムアウトに近づくため、速度面でも uv が有利である。

## OCI CLI

初期設定 (`oci setup config`) と OCID の取得に使う。構築後の運用では使わない (VM 側はインスタンスプリンシパルで認証する)。

```bash
uv tool install oci-cli
oci setup config
oci iam region list        # 疎通確認
```

対話で聞かれる項目と取得場所は [docs/manual/01-prerequisites.md](../manual/01-prerequisites.md) にある。

## Ansible (WSL2)

Windows はコントロールノードにできないため WSL2 に入れる。

```bash
sudo apt update && sudo apt install -y ansible-core
ansible --version          # ansible-core >= 2.16
```

WSL 側にも Tailscale が必要である。Windows 側で動いていても WSL からは別ホストとして見える。

```bash
curl -fsSL https://tailscale.com/install.sh | sh
sudo tailscale up --authkey=<tag:mc-admin のキー>
ssh ubuntu@mc-server       # 通ることを確認
```

詳細は [ansible/README.md](../../ansible/README.md)。

## 検証用 (任意)

静的検証を完全に通したい場合に使う。なくても構築はできる。

| ツール | 用途 | 導入 |
| --- | --- | --- |
| shellcheck | シェルスクリプトの静的解析 | `scoop install shellcheck` / `brew install shellcheck` |
| cloud-init | レンダリング結果のスキーマ検証 | WSL2 に `apt install cloud-init` |
| Docker | `docker compose config` で compose の妥当性確認 | Docker Desktop |

検証項目は [09. 検証方法](09-verification.md) にある。

## 確認

```bash
terraform -version                        # 1.16.3
uv --version
git --version
oci --version
wsl -e ansible --version                  # WSL2 に入れた場合

cd terraform && terraform validate
cd .. && uv run scripts/check-consistency.py
```
