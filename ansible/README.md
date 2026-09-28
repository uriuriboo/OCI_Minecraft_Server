# ansible/

**ここは構成管理の主体ではありません。** 初回構築は Terraform + cloud-init で完結しており、`terraform apply` だけでサーバーは動きます。

このディレクトリが担うのは「**VM を作り直さずに差し替えたいもの**」だけです。

| タグ | 対象ホスト | 配送するもの |
| --- | --- | --- |
| `app` | mc-server | `docker-compose.yml`、`.env` (playit キー / ホワイトリスト / プラグイン / MEMORY) |
| `monitor` | mc-monitor | `monitor.py`、`.env` (閾値 / `FILESYSTEM_NAME`)、systemd unit |

境界の判断基準は [docs/spec/02-architecture.md](../docs/spec/02-architecture.md) にあります。要点は、OCI が `metadata.user_data` の変更でインスタンスを置換し、それがワールド消失を意味するためです。

## 実行環境

Ansible は **Windows をコントロールノードとしてサポートしません**。以下のいずれかから実行してください。

### WSL2 (推奨)

```bash
sudo apt update && sudo apt install -y ansible-core
ansible --version        # ansible-core >= 2.16 が必要
```

`ansible.builtin.systemd_service` モジュールを使うため 2.16 以上が必要です。

WSL 側にも Tailscale が必要です。Windows 側で Tailscale が動いていても、WSL からは別ホストとして見えます。

```bash
curl -fsSL https://tailscale.com/install.sh | sh
sudo tailscale up --authkey=<tag:mc-admin のキー>
ssh ubuntu@mc-server     # 通ることを確認
```

### mc-monitor 上から

既に tailnet 内にいるため SSH の準備が不要です。リポジトリを持ち込んでください。

```bash
/home/ubuntu/venv/bin/pip install ansible-core
```

### Ansible を使わない場合

`monitor` タグ相当のことだけなら、scp と systemctl で済ませるスクリプトがあります。

```bash
./scripts/deploy-monitor.sh
```

## 使い方

```bash
# 1. Terraform で ansible/files/ を生成する (必須)
cd ../terraform && terraform apply

# 2. インベントリを用意する (初回のみ)
cd ../ansible && cp inventory_sample.yml inventory.yml

# 3. 差分を確認してから適用する
ansible-playbook site.yml -t app --check
ansible-playbook site.yml -t app

ansible-playbook site.yml -t monitor
ansible-playbook site.yml              # 両方
```

`files/` が無い状態で実行するとプレイブックが最初のタスクで止まり、`terraform apply` を促します。

## files/ について

`files/` は **Terraform が生成します**。`.gitignore` 済みで、RCON パスワードや Discord Webhook URL を含みます。

| ファイル | 生成元 |
| --- | --- |
| `files/docker-compose.yml` | `terraform/templates/docker-compose.yml.tftpl` |
| `files/mc-server.env` | `terraform/templates/mc-server.env.tftpl` |
| `files/mc-monitor.env` | `terraform/templates/mc-monitor.env.tftpl` |

`monitor.py`、`requirements.txt`、systemd unit は `files/` を経由せず、`../monitor/` から直接配送します。そちらが唯一の正です。

**このディレクトリに Jinja2 テンプレートを置かないでください。** 同じ `docker-compose.yml` を Terraform と Ansible の2箇所で管理すると必ず乖離します。設定を変えたいときは `terraform.tfvars` かテンプレート側を直してください。

## 設計上の注意

| 項目 | 内容 |
| --- | --- |
| `become` を使っていない箇所 | 接続ユーザーが既に `ubuntu` で docker グループにいるため。非特権ユーザーへの `become` は一時ファイルの権限で躓きやすい |
| `no_log: true` | `.env` の配送タスクに付けている。差分が標準出力に出ると秘密が漏れる |
| `daemon_reload` | unit ファイルを変えたら必須。しないと古い設定のまま動き続ける |
| 単発実行による確認 | `monitor` タグの最後で `mc-monitor.service` を1回走らせ、journal を表示する。配送したものが実際に動くかをその場で確かめるため |
| SSH 鍵の指定なし | Tailscale SSH がサーバー側で認証するため。`ansible.cfg` で `remote_user = ubuntu` のみ指定 |
