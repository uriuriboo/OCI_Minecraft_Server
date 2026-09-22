#!/usr/bin/env python3
"""docs/spec/ から docs/wiki/ のページを生成する。

GitHub wiki はフラットな名前空間でディレクトリを持てず、リンクの書式も
リポジトリ内の相対パスとは違う。そのため wiki のページは手で書かず、
docs/spec/ を唯一の正として機械的に変換する。

    python scripts/sync-wiki.py            # 生成
    python scripts/sync-wiki.py --check    # 差分があれば終了コード1 (CI用)

変換内容:
  docs/spec/04-monitoring.md          → docs/wiki/Spec-04-monitoring.md
  [x](02-architecture.md)             → [x](Spec-02-architecture)
  [x](../manual/06-operations.md)     → GitHub のリポジトリ上のファイルへの絶対リンク
  [x](../../terraform/variables.tf)   → 同上

手書きで維持するのは docs/wiki/Home.md と docs/wiki/_Footer.md、docs/wiki/README.md のみ。
_Sidebar.md はこのスクリプトが生成する。
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SPEC = ROOT / "docs" / "spec"
WIKI = ROOT / "docs" / "wiki"

# リポジトリ上のファイルへリンクするときの基点。
# fork や rename に追従できるよう、ここだけ直せば済むようにしている。
REPO_BLOB = "../blob/main"

GENERATED_HEADER = (
    "<!-- このページは docs/spec/{src} から生成しています。直接編集しないでください。\n"
    "     修正は docs/spec/ 側に入れて `python scripts/sync-wiki.py` を実行してください。 -->\n\n"
)

TITLES = {
    "00-introduction": "概要",
    "01-requirements": "要件",
    "02-architecture": "アーキテクチャ",
    "03-network-security": "ネットワーク・セキュリティ",
    "04-monitoring": "監視",
    "05-backup": "バックアップ",
    "06-operations": "運用・保守",
    "07-tech-stack": "構成技術・バージョン",
    "08-parameters": "パラメータ",
    "09-verification": "検証方法",
    "10-ownership": "担当者",
    "A1-doc-reconciliation": "手順書との差分",
    "A2-toolchain": "ツール導入",
}


def spec_pages() -> list[Path]:
    return sorted(p for p in SPEC.glob("*.md") if p.name != "README.md")


def convert(text: str, src_name: str) -> str:
    """spec/ の Markdown を wiki 用に書き換える。"""

    def repl(m: re.Match) -> str:
        label, target = m.group(1), m.group(2)

        # 同じディレクトリの spec ページ → wiki のページ名
        anchor = ""
        if "#" in target:
            target, anchor = target.split("#", 1)
            anchor = "#" + anchor

        if re.fullmatch(r"[\w.-]+\.md", target):
            stem = target[:-3]
            if (SPEC / target).exists():
                # ラベルがファイル名そのままだと wiki 上で読みにくいので章タイトルに直す。
                # 文章中で意味のあるラベルが付いている場合はそのまま残す。
                if label == target and stem in TITLES:
                    num = stem.split("-")[0]
                    label = f"{num}. {TITLES[stem]}"
                return f"[{label}](Spec-{stem}{anchor})"

        # 親ディレクトリ参照 (../manual/... , ../../terraform/... ) → リポジトリ上のファイル
        # docs/spec/ からの実際の相対パスを解決してから REPO_BLOB に載せる。
        # ".." の個数はソース側のネスト位置に依存するため、文字列の先読みではなく
        # パス解決で吸収する。
        if target.startswith("../"):
            resolved = (SPEC / target).resolve()
            rel = resolved.relative_to(ROOT.resolve())
            return f"[{label}]({REPO_BLOB}/{rel.as_posix()}{anchor})"

        return m.group(0)

    text = re.sub(r"\[([^\]]+)\]\(([^)\s]+)\)", repl, text)
    return GENERATED_HEADER.format(src=src_name) + text


def build_sidebar() -> str:
    lines = [
        "<!-- markdownlint-disable MD041 -->\n",
        "<!-- scripts/sync-wiki.py が生成しています。直接編集しないでください。 -->\n",
        "### 仕様書\n",
    ]
    for p in spec_pages():
        stem = p.stem
        title = TITLES.get(stem, stem)
        num = stem.split("-")[0]
        lines.append(f"- [{num}. {title}](Spec-{stem})")
    lines += [
        "\n### 手順書\n",
        "- [手順書の一覧](Runbook-Index)",
        f"- [docs/manual/ をリポジトリで見る]({REPO_BLOB}/docs/manual)",
        "\n### リンク\n",
        f"- [terraform/]({REPO_BLOB}/terraform)",
        f"- [monitor/]({REPO_BLOB}/monitor)",
        f"- [ansible/]({REPO_BLOB}/ansible)",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    check = "--check" in sys.argv
    WIKI.mkdir(exist_ok=True)

    planned: dict[Path, str] = {}
    for p in spec_pages():
        planned[WIKI / f"Spec-{p.name}"] = convert(p.read_text(encoding="utf-8"), p.name)
    planned[WIKI / "_Sidebar.md"] = build_sidebar()

    stale = 0
    for dest, content in planned.items():
        current = dest.read_text(encoding="utf-8") if dest.exists() else None
        if current == content:
            continue
        stale += 1
        if check:
            print(f"差分あり: {dest.relative_to(ROOT)}")
        else:
            dest.write_text(content, encoding="utf-8", newline="\n")
            print(f"{'更新' if current is not None else '作成'}: {dest.relative_to(ROOT)}")

    # spec から消えた章のページが残っていたら知らせる
    expected = {d.name for d in planned}
    for orphan in sorted(WIKI.glob("Spec-*.md")):
        if orphan.name not in expected:
            print(f"孤立: {orphan.relative_to(ROOT)} (docs/spec/ に対応する章がありません)")
            stale += 1

    if check:
        if stale:
            print(f"\nNG: {stale} 件。`python scripts/sync-wiki.py` を実行してください")
            return 1
        print("OK: docs/wiki/ は docs/spec/ と同期しています")
        return 0

    if not stale:
        print("変更なし")
    return 0


if __name__ == "__main__":
    sys.exit(main())
