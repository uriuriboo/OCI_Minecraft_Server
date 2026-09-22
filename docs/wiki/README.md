# docs/wiki/ の扱い

このディレクトリは **GitHub wiki に公開する内容** です。GitHub の wiki はリポジトリ本体とは別の Git リポジトリ (`<repo>.wiki.git`) なので、ここに置いたファイルを手動で反映します。

このファイル (`README.md`) は運用メモなので wiki には push しません。

## ファイルの区分

| ファイル | 生成方法 |
| --- | --- |
| `Spec-*.md` | **生成物**。`docs/spec/*.md` から `scripts/sync-wiki.py` が作る。直接編集しない |
| `_Sidebar.md` | **生成物**。同上 |
| `Home.md` | 手書き |
| `Runbook-Index.md` | 手書き。`docs/manual/` へのリンク集 |
| `_Footer.md` | 手書き |

`docs/spec/` を直したら必ず同期します。

```bash
python scripts/sync-wiki.py            # 生成
python scripts/sync-wiki.py --check    # 差分があれば終了コード 1 (CI 用)
```

`scripts/check-consistency.py` も「`docs/spec/` の各章に対応する wiki ページがあるか」を検査します。

## 公開手順

GitHub 上でリポジトリの Wiki を有効にし、一度でもページを作成してから (`.wiki.git` はそれまで存在しません) 以下を実行します。

```bash
# 1. wiki リポジトリを別の場所にクローン
cd /tmp
git clone https://github.com/<owner>/<repo>.wiki.git

# 2. このディレクトリの内容をコピー (README.md は除く)
cd <repo>.wiki
cp /path/to/minecraft_oci/docs/wiki/*.md .
rm -f README.md

# 3. push
git add -A
git commit -m "Sync wiki from docs/spec/"
git push
```

## リンクの書き方

`sync-wiki.py` が変換を担うので、`docs/spec/` 側では**通常のリポジトリ内相対パス**で書いてください。

| `docs/spec/` での記述 | wiki での結果 |
| --- | --- |
| `[04-monitoring.md](04-monitoring.md)` | `[04. 監視](Spec-04-monitoring)` |
| `[06-operations.md](06-operations.md) の変更管理` | ラベルはそのまま、リンク先のみ変換 |
| `[terraform/variables.tf](../../terraform/variables.tf)` | `../blob/main/terraform/variables.tf` |
| `[docs/manual/07-operations.md](../manual/07-operations.md)` | 同様にリポジトリ上のファイルへ |

リポジトリへのリンクの基点は `sync-wiki.py` の `REPO_BLOB` 定数 (既定 `../blob/main`) です。既定ブランチが `main` 以外の場合はここを変えてください。

## 注意

- GitHub wiki はディレクトリを持てないため、ページ名を `Spec-` 接頭辞でフラットにしています
- `_Sidebar.md` と `_Footer.md` はアンダースコア始まりが必須です (GitHub の予約名)
- wiki は**リポジトリの権限とは別に**書き込み権限を設定できます。公開リポジトリで wiki を誰でも編集できる状態にしないよう、Settings → Wikis の「Restrict editing to collaborators only」を確認してください
