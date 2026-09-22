---
name: setup-preflight
description: このリポジトリ (OCI Minecraft IaC) で環境構築に必要な値が揃っているかを apply 前に検査する手順。terraform.tfvars の必須変数・プレースホルダの残り・綴り違い・値の形式、~/.oci/config の APIキー認証、SSH 鍵、手元のツール、Ansible 側の inventory までを見る。「環境構築に必要な変数が足りているか」「tfvars を書いたので確認して」「何を用意すればいい」「apply する前に確認」「事前準備」「preflight」「セットアップの確認」「設定が正しいか見て」のような話が出たら必ずこのスキルを使うこと。`terraform validate` は値を見ないので代わりにならない。
---

# 構築前の値の点検 (preflight)

`terraform apply` は**値が足りないことを実行時にしか教えてくれない**。しかもこのリポジトリは
OCI の Always Free 枠に VM を 2 台立てる構成で、`plan` すら OCI の APIキー認証が通らないと走らない。
つまり「認証が通る前に、手元だけで分かることを全部潰しておく」必要がある。

このリポジトリで実際に確かめた `terraform` の挙動:

| 状況 | terraform の反応 |
| --- | --- |
| 必須変数が未設定 | `validate` は **exit 0**。`plan` まで行かないと出ない（= OCI 認証が要る） |
| tfvars に宣言のない名前 | **警告だけ**で apply は通る。既定値のある変数の綴り違いは黙って無視される |
| 値の中身が誤り（プレースホルダのまま、OCID の種別違い） | 型が合っていれば通る。API 呼び出しまたは VM 起動後に失敗する |

`scripts/check-consistency.py` は**リポジトリの中**が食い違っていないかを見るもので、
利用者が入れた値は見ていない。このスキルはその外側を見る。

## 進め方

1. **点検** — `uv run .claude/skills/setup-preflight/scripts/preflight.py` を実行する。
   NG が 1 件でもあれば exit 1 になる。
2. **NG を潰す** — 値の入手元は `docs/manual/01-prerequisites.md`（手順1〜8）が正。
   変数と入手元の一覧は `docs/spec/08-parameters.md`。
   スクリプトは `08-parameters.md` の表から入手元を読んで NG 行に添えるので、まずそれに従う。
3. **警告を読む** — apply は止めないが、意図した設定か必ず確認する（下の表）。
4. **再点検** — NG がゼロになってから `cd terraform && terraform plan` に進む。
   **`plan` に `must be replaced` が出たら apply せずに止まる**（既存 VM があるとき）。
5. **構築後** — `--day2` を付けて再度実行し、Ansible 側（`inventory.yml` / `ansible/files/`）を見る。

```bash
uv run .claude/skills/setup-preflight/scripts/preflight.py            # 初回構築前
uv run .claude/skills/setup-preflight/scripts/preflight.py --online   # + 現在のグローバルIPと照合
uv run .claude/skills/setup-preflight/scripts/preflight.py --day2     # + Ansible 側
```

`--online` だけが外に出る（`ifconfig.me`）。それ以外は OCI にも Tailscale にも繋がない。

## 見ているもの

| 節 | 内容 |
| --- | --- |
| 手元のツール | terraform の版が `.terraform-version` と一致するか（tenv 経由で起動しているか）、uv、`terraform init` 済みか |
| OCI 認証 | `~/.oci/config` の `[DEFAULT]` に user / fingerprint / key_file / tenancy / region があるか、key_file が実在するか、tenancy が tfvars とずれていないか。`provider "oci"` は region しか書いていない = APIキー認証が前提 |
| 入力ファイル | `terraform/terraform.tfvars` の有無、**それが git の管理下に入っていないか** |
| 変数の充足 | 既定値のない変数が埋まっているか、宣言にない名前（綴り違い候補つき）、既定値のまま残っている変数 |
| 値の形 | サンプルの値のまま / プレースホルダ（`xxxxx`、`<account-id>` 等）/ OCID の種別 / CIDR / webhook URL / MCID / 前後の空白・改行の混入 |
| 組み合わせ | 下の表 |
| SSH 鍵 | `ssh_public_key` に対応する秘密鍵が `~/.ssh/` にあるか（初回フォールバック SSH に要る） |
| Ansible (`--day2`) | `inventory.yml`、`ansible/files/` の生成、ansible-playbook の所在（Windows はコントロールノードにできない） |

値そのものは出力しない。`sensitive = true` の変数は「設定済み (N文字)」としか出さない。
ただし tfvars を読んで判定するので、**出力をそのまま外部に貼らない**。

## terraform が拾わない組み合わせ

`variables.tf` の validation で弾けるものは弾いている（`enable_home_ssh` と `home_ip_cidr`、
ZeroTier の 2 つ）。それ以外はここで見る。

| 検査 | 放置するとどうなるか |
| --- | --- |
| Tailscale の 2 本のキーが同じ値 | タグが 1 種類しか付かず、ACL の SSH ポリシーが効かない |
| `rcon_password` に空白 / `"` `'` `$` `#` `\` | `.env` を docker compose が解釈して壊れる。**RCON 認証が理由の分からない失敗をする** |
| 値の前後の空白・改行 | 同上（`\r` が値末尾に付くのと同じ事故） |
| `exposure_mode = playit` で `playit_secret_key` が空 | playit コンテナが `exit 1` で即終了する（初回は空でよい。後から Ansible の `app` タグで配送する） |
| `exposure_mode = playit` で `mc_whitelist` が空 | 公開アドレスに誰でも入れる。Tailscale ACL は IP しか見ないので MCID 制御はここだけ |
| `mc_ops` が空 | ゲーム内から管理する手段がない |
| `mc_router_auto_scale = true` | 停止中に monitor.py が DOWN と誤報し `backup.sh` も実行できない |
| `home_ip_cidr` が現在のグローバルIPと違う（`--online`） | 初回の SSH フォールバックが自分に効かない |
| `enable_home_ssh = false` | Tailscale 疎通を確認する前に閉じると**どこからも入れない** |
| `monitor_thresholds` の部分指定 | オブジェクト型なので 4 キー揃わないと apply が落ちる |
| `filesystem_name` が `/` のまま | ディスク使用率が取得できない。構築後に実測値へ直す（`docs/manual/02-post-setup.md` 手順8） |
| R2 バケット | Terraform は作らない。Cloudflare 側で作成済みか確認する（OCI 側のバケットは作る） |

## 段階

このリポジトリは **`terraform apply` だけで稼働状態に到達する**（Ansible は day-2 専用）。
点検すべき対象も段階で変わる。

| 段階 | 通すもの |
| --- | --- |
| 初回 apply 前 | 既定の実行。NG ゼロが条件 |
| apply 後 | `filesystem_name` を実測値へ、`playit_secret_key` を発行して投入、Tailscale 疎通を確認してから `enable_home_ssh = false` |
| day-2 更新 | `--day2`。`ansible/files/` は `terraform apply` の生成物なので、先に apply |

## 限界

- **OCI 側の実在は見ない。** コンパートメント OCID が実在するか、APIキーが有効か、
  Auth Key が期限切れでないかは分からない。形式と有無だけを見る。
- **heredoc (`<<-EOT`) の値は解釈しない。** tfvars では使わない前提。
  解釈できなかった値は形式検査から外れる（未設定扱いにはしない）。
- **`terraform plan` の代わりにはならない。** 型エラーと variable validation は plan が正。

## スクリプトを直したとき

```bash
uv run python -m py_compile .claude/skills/setup-preflight/scripts/preflight.py
uv run .claude/skills/setup-preflight/scripts/preflight.py          # 実際に通す
```

`terraform/variables.tf` に変数を足したら、`terraform.tfvars_sample` と
`docs/spec/08-parameters.md` にも足す（`scripts/check-consistency.py` が検出する）。
スクリプト側は variables.tf と仕様書の表を読むので、**変数名の一覧は持っていない**。
持っているのは「形式」「組み合わせ」「サンプルのままだと困るもの (`MUST_CHANGE`)」の 3 つだけ。
新しい秘密を足したら `MUST_CHANGE` に追加する。
