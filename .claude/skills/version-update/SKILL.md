---
name: version-update
description: このリポジトリ (OCI Minecraft IaC) で固定しているバージョンを棚卸しし、更新する手順。Terraform 本体・OCI/local プロバイダ・playit-agent のイメージタグ・Python 依存 (pyproject.toml と monitor/requirements.txt)・uv/tenv/ansible-core が対象。「バージョン更新」「依存を上げたい」「最新版を調べて」「terraform init -upgrade」「uv pip compile したい」「playit のタグを上げたい」「プロバイダを上げたい」「棚卸し」「outdated」のような話が出たら必ずこのスキルを使うこと。単に「最新版は何か」を聞かれただけでも、定義場所と更新後の検証がセットで必要なのでこのスキルを読むこと。
---

# バージョン更新

このリポジトリは**ピン留めを意図的に多層化している**。無人で動く Minecraft サーバーが、
誰も見ていない時間に破壊的変更を拾わないようにするためである。
その代償として「どこを直せば実際に反映されるのか」が分散している。このスキルはそれを一箇所にまとめる。

**Python は uv だけで扱う。`pip install` は使わない**（VM 上の `uv pip sync` は uv のサブコマンドなので該当しない）。
補助スクリプトは `uv run` で起動する。

## 進め方

1. **棚卸し** — `uv run .claude/skills/version-update/scripts/survey.py` を実行する。
   リポジトリ内のピン留めを読み、upstream の最新版と突き合わせた表を出す。
2. **更新対象を決める** — 下の「対象ごとの手順」を読み、リスクを添えてユーザーに確認する。
   特に OCI プロバイダのメジャー更新と Minecraft 系は**ワールド消失に繋がりうる**ので独断で進めない。
3. **適用** — 対象ごとの手順に従う。
4. **検証** — 「検証」節を上から順に通す。変更した領域に対応する検証を飛ばさない。
5. **記録** — `docs/spec/07-tech-stack.md` の一覧表を実態に合わせ、`uv run scripts/sync-wiki.py` を実行する。

## 対象ごとの手順

### Terraform 本体

`terraform/.terraform-version` が正（tenv が読む）。`terraform/versions.tf` の
`required_version = "~> 1.9"` は**下限であって固定ではない**ので、1.x の範囲なら触らなくてよい。
下限を上げてよいのは 1.9 より新しい機能に依存し始めたときだけで、今は変数をまたぐ validation
（1.9 の機能）にだけ依存している。

```bash
scoop install tenv          # 未導入なら。tenv 経由でないと .terraform-version が効かない
tenv tf install             # .terraform-version を読んで入れる
cd terraform && terraform validate
```

`docs/spec/A2-toolchain.md` に `terraform -version` の期待出力が**バージョン番号ごと**書かれている。
ここも一緒に直さないと手順書が嘘になる。

### Terraform プロバイダ

`versions.tf` の制約を変え、lock を更新する。lock ファイルはコミットする。

```bash
cd terraform
terraform init -upgrade
terraform plan             # 差分を必ず読む
```

**`plan` に `must be replaced` が出たら、そこで止めてユーザーに報告する。**
インスタンスの置換はブートボリューム破棄 = ワールド消失を意味する。
プロバイダのメジャー更新は属性の既定値が変わって置換を誘発することがあり、これが一番危ない経路である。

lock だけ更新したい（制約は据え置き）ときは `terraform init -upgrade` だけでよい。

`scripts/render-check/` も独自の lock を持っている。local プロバイダを上げたならこちらも
`terraform init -upgrade` する。

### playit-agent のイメージタグ

`terraform/templates/docker-compose.yml.tftpl` の `image:` が唯一の正。
cloud-init と `ansible/files/` の両方がここから生成される。

**エントリポイントが読む環境変数を必ず確認してから上げる。** このイメージは
`docker/entrypoint.sh` で秘密鍵を受け取っており、**値が空だと `exit 1` で即終了する**。
変数名が変わっていれば `terraform/templates/mc-server.env.tftpl`、`env/mc-server.env_sample`、
`terraform/variables.tf`、`docs/spec/02-architecture.md`・`03-network-security.md`・`08-parameters.md`
まで波及する。

```bash
# タグ一覧と、そのタグのエントリポイントを読む
uv run .claude/skills/version-update/scripts/survey.py --playit-entrypoint v1.0.10
```

反映は `terraform apply` → `ansible-playbook site.yml -t app`。

### Python 依存

直接依存の制約は `pyproject.toml` の `[dependency-groups] monitor` にだけ書く。
`monitor/requirements.txt` は生成物なので**手で編集しない**。

```bash
uv pip compile pyproject.toml --group monitor \
  --python-version 3.12 --python-platform x86_64-unknown-linux-gnu \
  -o monitor/requirements.txt
```

`--python-version` / `--python-platform` は mc-monitor (Ubuntu 24.04 / x86_64) に合わせている。
省略すると手元の Python 向けに解決され、VM に入らない版がピン留めされる。
`scripts/check-consistency.py` がヘッダのコマンド行を検査してこれを捕まえる。

制約は据え置きで推移的依存だけ上げたいときは `--upgrade` を足す。
反映は `ansible-playbook site.yml -t monitor`。

### 手元のツール

| 対象 | 確認 | 更新 |
| --- | --- | --- |
| uv | `uv --version` | `uv self update` |
| tenv | `tenv --version` | `scoop update tenv` / `brew upgrade tenv` |
| ansible-core | `ansible --version` | WSL2 で `apt upgrade ansible-core`（Windows はコントロールノードにできない） |

### 上げないと判断してよいもの

- **Ubuntu** — `data.oci_core_images` が 24.04 の最新を取る。メジャーを上げると
  VM 再作成 = ワールド消失なので、`operating_system_version` は据え置きが既定。
  そもそも OCI に新 LTS のイメージが載るまで時間差がある。
- **latest 追従組** — `itzg/minecraft-server`、`itzg/mc-router`、`itzg/mc-backup`、
  Tailscale、ZeroTier。設計としてピン留めしていない。
  mc-router だけは更新後に playit 経由で実際に接続して経路を確認すること
  （`DEFAULT` / `IN_DOCKER` の環境変数名が変わると黙って繋がらなくなる）。
- **SpigotMC のプラグイン ID** — ID は版ではない。SPIGET が実行時に最新を取る。

### Minecraft 本体

`VERSION=LATEST` なので明示的な更新操作はないが、**メジャーが上がるとプラグイン互換が壊れる**。
上げる話が出たら先にバックアップを促す。

```bash
ssh ubuntu@mc-server '~/minecraft/backup.sh'
```

## 検証

クラウド認証なしで通せるものから順に。**テンプレートを触ったら 2 以降を必ず通す。**
`terraform validate` は HCL の構文しか見ず、**テンプレートの出力が壊れていても通る**。

```bash
# 1. 静的検査
cd terraform && terraform fmt -check -recursive && terraform validate
uv run scripts/check-consistency.py
uv run scripts/sync-wiki.py --check

# 2. テンプレートのレンダリング (exposure_mode 3値 + 分岐を一度に出す)
cd scripts/render-check && terraform apply -auto-approve -var proj=../..
cd ../.. && uv run scripts/check-rendered.py scripts/render-check/out

# 3. シェルの構文 (2 では見ていない)
wsl -e bash -c 'cd scripts/render-check/out && bash -n backup.sh backup.min.sh playit-check.sh'

# 4. Python
uv run python -m py_compile monitor/monitor.py
```

VS Code の `check: すべて` タスクが 1 と 4 をまとめて実行する。

実環境での受入試験は `docs/spec/09-verification.md` が正。

## 忘れやすいこと

- **改行コード** — VM へ配るファイルが CRLF になると壊れる（`.env` の値末尾の `\r` で
  RCON 認証が理由不明に失敗する、など）。この環境は `core.autocrlf = true` なので、
  新しく作るファイルは LF で書く。`check-consistency.py` と `check-rendered.py` が検査する。
- **`templatefile` のエスケープ** — `$${` と `%%{` だけがエスケープ。`$((expr))` はそのまま書く。
  `$$((expr))` は誤りで、bash で `$$` が PID に展開される。目視では気づけないので 2 と 3 を通す。
- **ドキュメントを置き去りにしない** — `docs/spec/07-tech-stack.md` にはソフトウェア一覧と
  「バージョン更新対象一覧」の両方にバージョンが書かれている。`docs/spec/A2-toolchain.md` にも
  期待出力として書かれている。直したら `uv run scripts/sync-wiki.py`。
  `docs/manual/` は実装と食い違いがあれば直接修正する。修正・仕様と食い違う判断をしたら `docs/spec/A1-doc-reconciliation.md` に追記する。
- **生成物を手編集しない** — `monitor/requirements.txt`、`docs/wiki/Spec-*.md`、`docs/wiki/_Sidebar.md`、
  `ansible/files/*`、`scripts/render-check/out/*`。
- **cloud-init の変更は既存 VM に届かない** — 両インスタンスに `ignore_changes = [metadata, ...]`
  が付いている。cloud-init に閉じた変更は手で入れるか Ansible の対象に足す。
