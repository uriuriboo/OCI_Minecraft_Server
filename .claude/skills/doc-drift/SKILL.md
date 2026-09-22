---
name: doc-drift
description: このリポジトリ (OCI Minecraft IaC) のドキュメントが実装と食い違っていないかを点検し、直す手順。docs/spec・docs/manual・docs/wiki・README・CLAUDE.md を対象に、リンク切れ、存在しないファイル/変数/出力/Ansible タグの参照、パラメータ表の既定値と sensitive、.env の変数名、文章に埋め込まれた固定値 (バージョン・ポート・IP・監視間隔・イメージタグ) をコードと突き合わせる。「ドキュメントが実装と合っているか確認」「仕様書と実装の突き合わせ」「docs の点検」「ドキュメントが古くないか」「更新漏れ」「陳腐化」「doc drift」「手順書が実装と違う」のような話が出たら必ずこのスキルを使うこと。コードを変えた後にドキュメントを直す場面でも読むこと。
---

# ドキュメントと実装の突き合わせ

このリポジトリはドキュメントが 3 層あり、**どれを直すかを間違えると次の生成で消える**。
食い違いを見つけたら、まず「どの層の問題か」を決める。

| 層 | 役割 | 食い違いを見つけたら |
| --- | --- | --- |
| `docs/spec/` | 仕様書（何を・なぜ）。**正** | ここを直す。直したら `uv run scripts/sync-wiki.py` |
| `docs/manual/` | 構築時の手順書 | **実装に合わせて直接修正してよい。** 修正内容を `docs/spec/A1-doc-reconciliation.md` に記録する |
| `docs/wiki/` | GitHub wiki 用 | `Spec-*.md` と `_Sidebar.md` は生成物。**直接編集しない**。手書きは `Home.md` / `Runbook-Index.md` / `_Footer.md` のみ |

`CLAUDE.md` と `README.md` も検査対象に入れている（実際にここのバージョン番号が古くなっていた）。

**コードが常に正。** ドキュメントに合わせてコードを変えるのは、コード側がバグだと確認できたときだけ。

## 原則: 変わる値をドキュメントに書かない

食い違いを直すときは、**「値を書き写して同期させる」のではなく「値を消して定義場所を指す」**。
同期は必ず破れる。1 箇所上げるたびに複数の文書を直す運用は続かない
（実際に Terraform の版・playit のタグ・変数の個数が古くなっていた。`docs/spec/A1-doc-reconciliation.md` の 4-21）。

| 書かない | 代わりに書く |
| --- | --- |
| バージョンの数字（Terraform / プロバイダ / イメージのタグ / Python 依存の制約） | 定義場所のファイル名 |
| 個数（変数が何個、章が何本） | 数えられる場所への参照 |
| コードの全文コピー | 実装ファイルへのリンクと、そこから読み取れない設計意図 |
| 既定値の写し | `08-parameters.md` の表は例外。ここだけは表が一覧の役目を持つので値を書き、検査で守る |

例外は 2 つだけ。**コード側に置き場がない値**（ansible-core の下限など。`07-tech-stack.md` が唯一の正）と、
**なぜその下限なのかの説明**（「変数をまたぐ validation は 1.9 で入った」のような理由つきの言及）。

数字を書かない代わりに、現在値は次で出す。

```bash
uv run .claude/skills/doc-drift/scripts/check-docs.py --facts        # 実装から取れる値
uv run .claude/skills/version-update/scripts/survey.py               # + upstream の最新
```

## 進め方

1. **機械検査** — `uv run .claude/skills/doc-drift/scripts/check-docs.py`。NG があれば exit 1。
2. **事実の一覧を出す** — `... --facts`。実装から取れる値（版・shape・ポート・間隔・タグ）を並べる。
   機械で照合できない説明文を読むときの手元資料にする。
3. **層を決めて直す** — 上の表。`docs/spec/` を直したら `uv run scripts/sync-wiki.py`。
4. **`docs/manual/` を直したら A1 に記録** — `docs/spec/A1-doc-reconciliation.md` の該当する節
   （手順書どうしの不整合 / 手順書のコードのバグ / 実装との差分）に 1 行足す。
   **「どちらを正としたか」と理由**を書く。ここが後から読み返される唯一の場所になる。
5. **再検査** — 1 と、下の「検証」を通す。

```bash
uv run .claude/skills/doc-drift/scripts/check-docs.py
uv run .claude/skills/doc-drift/scripts/check-docs.py --facts
```

## 機械が見ているもの

`scripts/check-consistency.py` が「コードと設定ファイルの間」（テンプレート・サンプル・.gitignore・
改行コード）を見るのに対し、こちらは**ドキュメントとコードの間**を見る。重複はしていない。

| 分類 | 内容 |
| --- | --- |
| リンク | 相対リンクの実在。wiki は `Spec-xxx` のページ名と `../blob/main/<path>` の両形式 |
| ファイル参照 | 地の文・コードブロック中のリポジトリ相対パスの実在（`.gitignore` 済みの生成物は除外） |
| 変数名 / 出力名 | `var.xxx` が `variables.tf` に、`terraform output xxx` が `outputs.tf` にあるか |
| Ansible タグ | `site.yml -t <tag>` が `ansible/site.yml` の `tags` にあるか |
| 変数の値 | `exposure_mode = "..."` が validation の許容値に入っているか |
| パラメータ表 | `08-parameters.md` の変数の**過不足・既定値・秘(sensitive)**、出力の過不足、`.env` の変数名 |
| env サンプル | `env/mc-monitor.env_sample` の値が `variables.tf` の既定値と一致するか |
| 固定値 | Terraform の版 / playit のイメージタグ / shape / OCPU・メモリ / ブートボリューム / Ubuntu の版 / 監視間隔 / `TYPE` / `VERSION` / VCN 内のアドレス / プラグインのリソースID |
| 貼り付けコード | 文書に貼られた Python の `os.environ[...]` が `monitor.py` の実装と一致するか（必須か任意かも見る） |

値は**すべてコードから読む**。スクリプトの中に期待値を書いていない。
だから「コードを変えたらスクリプトも直す」必要はなく、**コードを変えたのに文書を直していないこと**だけが出る。

## 機械では見えないもの

ここから先は読んで判断する。`--facts` の出力を手元に置いて、次を見る。

| 観点 | 典型的な腐り方 |
| --- | --- |
| 「なぜその値なのか」の説明 | 値は一致しているが理由が古い（例: Always Free の枠が 4/24 から 2/12 に半減した経緯） |
| 手順の順序 | 実装が変わって手順の前提が崩れている（例: 先に ACL の `tagOwners` が要る） |
| 設計の前提 | `exposure_mode` の分岐、`ignore_changes` の副作用、`mc-router` に `docker.sock` を渡さない理由 |
| 図・表の構造 | コンテナ構成や NSG の表に、実装で増えた要素が載っていない |
| 削除された機能 | 実装から消えたのに手順書に残っている |

章ごとの「実装の正」はここ。文章を読むときはこの対応で突き合わせる。

| `docs/spec/` | 実装の正 |
| --- | --- |
| 02-architecture | `terraform/render.tf`、`compute.tf`、`templates/docker-compose.yml.tftpl`、`ansible/site.yml` |
| 03-network-security | `terraform/network.tf`、`terraform/cloud-init/*.tftpl` の iptables、`tailscale/acl.hujson` |
| 04-monitoring | `monitor/monitor.py`、`monitor/systemd/*`、`templates/mc-monitor.env.tftpl`、`dashboards/oci-dashboard.json` |
| 05-backup | `templates/backup.sh.tftpl`、`templates/rclone.conf.tftpl`、`terraform/storage.tf`、`scripts/restore.sh` |
| 06-operations | `ansible/site.yml`、`terraform/compute.tf` の `lifecycle`、`scripts/` |
| 07-tech-stack | `terraform/versions.tf`、`.terraform-version`、`pyproject.toml`、compose の `image:` |
| 08-parameters | `terraform/variables.tf`、`outputs.tf`、`templates/*.env.tftpl` |
| A2-toolchain | `.terraform-version`、`pyproject.toml`（期待出力にバージョン番号が直接書いてある） |

## 誤検知として扱ってよいもの

スクリプトは次を意図的に見ていない。増やすときはここに理由を書き足す。

- **`.gitignore` 済みのパス** — `terraform.tfvars`、`ansible/files/`、`ansible/inventory.yml` は
  「利用者が作る」「apply が生成する」ファイルで、リポジトリに無いのが正常。`git check-ignore` で除外している。
- **拡張子のない `tailscale/zerotier` のような表記** — 地の文（「mc-router を tailscale/zerotier に
  広げない」）とパスを区別できない。
- **`docs/manual/` のパス参照** — 警告止まりにしている。旧構成の名残（冒頭の `保存先:` 表記など）が残っている。
- **`monitor_thresholds` の既定値** — オブジェクト型で表には散文で書いてあるため突き合わせない。
- **`<tag>` のようなプレースホルダ** — 「値をここに書かない」という意図的な表記なので飛ばす。
- **散文の「5分ごと」** — 同じ表現を監視タイマー (5分) と `playit-check.sh` の cron (10分) の
  両方が使っており、文脈なしに区別できない。間隔は `OnUnitActiveSec=` の記法と
  「監視間隔 N 分」の形だけを見る。

## 検証

```bash
uv run python -m py_compile .claude/skills/doc-drift/scripts/check-docs.py
uv run .claude/skills/doc-drift/scripts/check-docs.py     # 実際に通す
uv run scripts/check-consistency.py                       # 別の観点。両方通す
uv run scripts/sync-wiki.py --check                       # spec を直したら
```

スクリプトを直したときは、**誤りをわざと入れて検出されることも確認する**。
`docs/spec/08-parameters.md` に既定値の誤り・存在しないリンク・宣言のない `var.x` を入れ、
検査後に `git checkout -- docs/spec/08-parameters.md` で戻す。
**戻す前に未コミットの変更が無いか確認すること**（`git checkout --` は同じファイルの他の修正も巻き戻す）。
