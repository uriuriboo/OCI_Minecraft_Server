# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

OCI の Always Free 枠で Minecraft (PaperMC) サーバーを運用するための IaC リポジトリ。受信ポートを一切開けない構成が前提。

## 環境上の注意

- **Bash ツールはこの環境で出力を返さない。** シェル作業は PowerShell ツールを使う。POSIX なシェルが必要な場合は `wsl -e bash <script>` を使い、**PowerShell から WSL へワンライナーを渡さない**（クォートが壊れてコマンドが実行されないまま成功に見える。実際にこれで CRLF のバグを一度見逃した）。スクリプトファイルにして渡すこと。
- **Ansible は Windows をコントロールノードにできない。** WSL2 または mc-monitor 上から実行する。

## コマンド

### 検証（クラウド不要・コード変更時は毎回通す）

```bash
cd terraform && terraform fmt -check -recursive && terraform validate
uv run scripts/check-consistency.py      # env変数/tfvars/gitignore/CRLF/requirements の整合性
uv run scripts/sync-wiki.py --check      # docs/wiki が docs/spec と同期しているか
uv run python -m py_compile monitor/monitor.py
```

VS Code の `check: すべて` タスクで上記をまとめて実行できる（`.vscode/tasks.json`）。

### テンプレートを変えたときの検証ループ（最重要）

`terraform validate` は HCL の構文しか見ない。**テンプレートの出力が壊れていても通る。**
`terraform/templates/` や `terraform/cloud-init/` を触ったら必ずこれを回す。

```bash
cd scripts/render-check
terraform init                                          # 初回のみ (local プロバイダだけ)
terraform apply -auto-approve -var proj=../..           # 3方式ぶん out/ に書き出す
cd ../..
uv run scripts/check-rendered.py scripts/render-check/out
```

`scripts/render-check/` は OCI 認証も要らない使い捨て構成で、`exposure_mode` の3値すべてと
「空リスト」「OCIバックアップ無効」「`mc_router_auto_scale=true`」の分岐を一度に出す。
**1つの方式だけ直して他を壊す事故を防ぐ。**

`check-rendered.py` は過去に実際に踏んだ2つのバグを回帰試験として持っている
（`$$((` の残留、CRLF の混入）ほか、`write_files` の欠落・`monitor.py` の途中切れ・
`permissions` のクォート漏れ・iptables の ACCEPT/DROP 順序・compose と iptables の矛盾・
mc-router の2形態（既定で `docker.sock` を渡していないこと）を検査する。

シェルスクリプトの構文は別途通す（この検査では見ていない）。

```bash
wsl -e bash -c 'cd scripts/render-check/out && bash -n backup.sh backup.min.sh playit-check.sh'
```

実環境での受入試験項目は `docs/spec/09-verification.md` が正。

### 適用

```bash
cd terraform && terraform apply                      # インフラ + ansible/files/ の生成
cd ansible && ansible-playbook site.yml -t app       # docker-compose.yml / .env の配送
cd ansible && ansible-playbook site.yml -t monitor   # monitor.py / .env / systemd unit の配送
```

### 生成物の再生成

```bash
uv run scripts/sync-wiki.py                          # docs/spec/ → docs/wiki/
uv run scripts/print-dashboard.py                    # terraform output から貼り付け用 MQL

# monitor.py の依存を変えたとき (pyproject.toml → monitor/requirements.txt)
uv pip compile pyproject.toml --group monitor --python-version 3.12 --python-platform x86_64-unknown-linux-gnu -o monitor/requirements.txt
```

`--python-version` / `--python-platform` は mc-monitor (Ubuntu 24.04 / x86_64) に合わせている。省略すると手元の Python 向けに解決され、別バージョンがピン留めされる。`check-consistency.py` がヘッダを検査して検出する。

### ツールチェーン

Terraform は tenv で `terraform/.terraform-version` に固定、Python は uv。導入手順は `docs/spec/A2-toolchain.md`。下限は `versions.tf` の `required_version` が持つ（`variables.tf` が変数をまたぐ validation を使うため）。**バージョンの数字はドキュメントに書かない**（定義場所だけ書く。値を持つと更新のたびに複数の文書を直すことになる）。

## アーキテクチャ

### Terraform 主体 / Ansible 最小の境界

判断基準は **「VM を作り直さずに変更したいか」** の一点。OCI は `metadata.user_data` の変更でインスタンスを置換し、それはブートボリューム破棄 = **ワールド消失**を意味する。

| | 担当 |
| --- | --- |
| 初回構築で確定し以後変わらない（apt / SSH / Tailscale / iptables / venv / systemd unit / rclone.conf / backup.sh、**初回の docker-compose.yml と .env** も含む） | Terraform + cloud-init |
| 稼働後に繰り返し変える（① monitor.py と閾値・`FILESYSTEM_NAME` ② docker-compose.yml と .env） | Ansible (`site.yml` の `app` / `monitor` タグ) |

`terraform apply` だけで稼働状態に到達する。**Ansible を一度も実行しなくてもサーバーは動く。** Ansible は day-2 更新専用。

両インスタンスに `lifecycle { ignore_changes = [metadata, source_details[0].source_id] }` が付いている。副作用として cloud-init に閉じた変更（iptables、パッケージ追加）は既存 VM に反映されない — 手で入れるか Ansible の対象に足す（`docs/spec/06-operations.md` の変更管理）。

**`terraform plan` に `must be replaced` が出たら apply せずに止まる。**

### テンプレートの単一の正

`terraform/templates/*.tftpl` が唯一の正。`terraform/render.tf` が 2 経路に配る。

```text
terraform/templates/docker-compose.yml.tftpl
        ├─ templatefile() → cloud-init に埋め込み（初回構築）
        └─ local_file      → ansible/files/（day-2 更新、.gitignore 済み）
```

**`ansible/` に Jinja2 テンプレートを置かない。** Ansible は `ansible/files/` の成果物を `copy` するだけの配送役。同じ docker-compose.yml を 2 箇所で管理すると必ず乖離する。

同様に `monitor/monitor.py` と `monitor/systemd/*` は `monitor/` が唯一の正で、Terraform（`file()` で読む）と Ansible（直接 copy）の両方がそこを参照する。

### exposure_mode の 3 分岐

`playit` (既定) / `tailscale` / `zerotier`。**どれでも 25565 の NSG ingress は作らない**（すべてアウトバウンド接続を使い回す方式）。1 つの変数が 2 箇所に影響する。

| | `playit` | `tailscale` / `zerotier` |
| --- | --- | --- |
| Docker ネットワーク | bridge (`mcnet`) + mc-router + playit-agent | `network_mode: host` |
| 25565 | ホストに出さない。playit → `mc-router:25565` → `mc:25565` | iptables で `-i tailscale0` / `-i zt+` のみ ACCEPT |
| 25575 (RCON) | `ports` でプライベートIPにバインド、NSG で制御 | iptables で VCN 内のみ ACCEPT |

playit で RCON を iptables で守らないのは、**Docker の DNAT が INPUT チェーンを通らない**ため。変更時は cloud-init と docker-compose の両テンプレートの整合を確認する。

**mc-router を tailscale/zerotier に広げないこと。** mc-router はコンテナ名でバックエンドに繋ぐので `mc` を bridge に移す必要があり、そうすると 25565 が Docker の公開ポートになって上記の理由で iptables が効かなくなる。

`mc_router_auto_scale` (既定 `false`) を `true` にすると mc-router に `docker.sock` が渡り、無人時に `mc` が停止する。停止中は monitor.py が DOWN と誤報し `backup.sh` も実行できない。既定を変えるなら先に `docs/spec/04-monitoring.md` の制約を読む。

### ドキュメントの三層

| | 役割 | 編集 |
| --- | --- | --- |
| `docs/spec/` | 仕様書（何を・なぜ）。**正** | ここを直す |
| `docs/manual/` | 構築時の手順書。**実装と食い違いがあれば直接修正する** | 判明した不整合・バグは修正してよい。修正内容は `docs/spec/A1-doc-reconciliation.md` に記録する |
| `docs/wiki/` | GitHub wiki 用 | `Spec-*.md` と `_Sidebar.md` は生成物。手書きは `Home.md` / `Runbook-Index.md` / `_Footer.md` のみ |

これまでに見つかったプレースホルダ・不整合・動かないコードは `docs/manual/` 側を修正済みで、**全件が `docs/spec/A1-doc-reconciliation.md` に「どちらを正としたか」と理由付きで記録されている。** 手順書と食い違う実装を新たに見つけたら、まずここを読み、`docs/manual/` を実装に合わせて直接修正し、ここに追記する。

`docs/spec/` を直したら `uv run scripts/sync-wiki.py` を実行する。

## 落とし穴

### Terraform テンプレートのエスケープ

`templatefile` がエスケープとして扱うのは `$${` と `%%{` **だけ**。

| 書き方 | 結果 | 用途 |
| --- | --- | --- |
| `$${VAR}` | `${VAR}` | compose の変数展開、シェルの変数参照 |
| `$(cmd)` / `$((expr))` | そのまま | シェルのコマンド置換・算術展開 |
| `$$((expr))` | **`$$((expr))`** | 誤り。bash で `$$` が PID に展開される |

レンダリング結果に対して実際に `bash -n` を通すこと。目視では気づけない。

### 改行コード

この環境は `git config core.autocrlf` が **`true`**。放っておくとチェックアウト時に全ファイルが CRLF になる。

VM へ配るファイルが CRLF になると壊れる（`backup.sh` の行継続が破綻、`.env` の値末尾に `\r` が付き **RCON 認証が理由の分からない失敗をする**、systemd が `ExecStart` を誤読）。cloud-init の `write_files` はテンプレートの中身をそのまま VM に埋め込むため、手元の改行コードがそのまま本番の不具合になる。

4 層で防いでいる。**どれも外さない。**

| 層 | 実装 |
| --- | --- |
| チェックアウト | `.gitattributes` の `* text=auto eol=lf` |
| レンダリング | `render.tf` の `replace(x, "\r\n", "\n")` |
| コミット前 | `check-consistency.py` の改行コード検査 |
| 出力検査 | `check-rendered.py` の CRLF 検査 |

新しいファイルを作ったら LF で書く。`.gitattributes` があるので `git add` 以降は正規化されるが、レンダリングは作業ツリーのファイルを直接読むため、ディスク上が CRLF だとその場で壊れる。

### 生成物を手編集しない

| ファイル | 生成元 |
| --- | --- |
| `monitor/requirements.txt` | `pyproject.toml` の `[dependency-groups] monitor` + `uv pip compile` |
| `docs/wiki/Spec-*.md`, `docs/wiki/_Sidebar.md` | `docs/spec/*.md` + `scripts/sync-wiki.py` |
| `ansible/files/*` | `terraform/render.tf` の `local_file` |
| `scripts/render-check/out/*` | `scripts/render-check` の apply |

### git の状態

- 既定ブランチは **`initial-setup`**（`main` ではない）。リモートは `github.com/uriuriboo/OCI_Minecraft_Server`。
- **`git status` で `docs/manual/` が `M` に見えることがあるが、`git diff --numstat -- docs/manual/` は 0 件。** 改行コードのみの差で内容は原本のまま。「直そう」としないこと。
- `todo.md` は `.gitignore` 済み。ユーザーの作業メモなのでコミットしない。

### その他

- `docs/spec/` と `docs/wiki/` の Markdown は表の区切りを `| --- |` のパディングスタイルで書く（markdownlint MD060）。`docs/manual/` は詰めスタイルだが原本なので直さない。
- `uv.lock` は `.gitignore` 済み。VM へ配る依存の正は `monitor/requirements.txt` で、lock は同じ依存グループを別の解決結果で二重に固定してしまうため。
- 秘密情報の投入口は `*_sample`（`terraform.tfvars_sample`、`env/*_sample`、`inventory_sample.yml`）。`check-consistency.py` が `.gitignore` の取りこぼしを検査する。
- `terraform/.terraform.lock.hcl` と `terraform/.terraform-version` はコミットする。`terraform/.terraform/`（プロバイダバイナリ 239MB）は無視する。
