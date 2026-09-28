#!/usr/bin/env python3
"""リポジトリ内の設定が食い違っていないかを静的に検査する。

クラウドに繋がずに実行できる。CI やコミット前の確認に使う。

    python scripts/check-consistency.py

検査内容:
  1. monitor.py が必須として読む環境変数が、Terraform テンプレートと
     env/*_sample の両方に存在すること
  2. terraform/variables.tf で宣言した変数が terraform.tfvars_sample に
     載っていること (既定値のないものは必須)
  3. .gitignore が秘密ファイルを取りこぼしていないこと
  4. docs/spec/ と docs/wiki/ の対応が取れていること
  5. monitor/requirements.txt が VM のターゲット指定で生成されていること
  6. VM へ配るファイルが CRLF になっていないこと
"""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
failures: list[str] = []
notes: list[str] = []


def fail(msg: str) -> None:
    failures.append(msg)


def read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


# ---------------------------------------------------------------- 1. 環境変数

def monitor_env_vars() -> tuple[set[str], set[str]]:
    """monitor.py から (必須, 任意) の環境変数名を抜き出す。

    os.environ["X"]     → 必須
    os.environ.get("X") → 任意 (コード側に既定値がある)
    """
    tree = ast.parse(read("monitor/monitor.py"))
    required: set[str] = set()
    optional: set[str] = set()

    for node in ast.walk(tree):
        # os.environ["X"]
        if (
            isinstance(node, ast.Subscript)
            and isinstance(node.value, ast.Attribute)
            and node.value.attr == "environ"
            and isinstance(node.slice, ast.Constant)
            and isinstance(node.slice.value, str)
        ):
            required.add(node.slice.value)
        # os.environ.get("X", ...)
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "get"
            and isinstance(node.func.value, ast.Attribute)
            and node.func.value.attr == "environ"
            and node.args
            and isinstance(node.args[0], ast.Constant)
            and isinstance(node.args[0].value, str)
        ):
            optional.add(node.args[0].value)

    return required, optional


def env_keys(text: str) -> set[str]:
    """KEY=VALUE 形式のキーを拾う。コメント行は無視する。"""
    keys = set()
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        m = re.match(r"^([A-Z_][A-Z0-9_]*)=", line)
        if m:
            keys.add(m.group(1))
    return keys


def check_monitor_env() -> None:
    required, optional = monitor_env_vars()
    notes.append(f"monitor.py: 必須={len(required)} 任意={len(optional)}")

    tftpl = env_keys(read("terraform/templates/mc-monitor.env.tftpl"))
    sample = env_keys(read("env/mc-monitor.env_sample"))

    for name in sorted(required):
        if name not in tftpl:
            fail(
                f"monitor.py が必須とする {name} が "
                f"terraform/templates/mc-monitor.env.tftpl にない "
                f"(VM 上で KeyError になる)"
            )
        if name not in sample:
            fail(f"monitor.py が必須とする {name} が env/mc-monitor.env_sample にない")

    known = required | optional
    for name in sorted(tftpl - known):
        fail(f"mc-monitor.env.tftpl の {name} を monitor.py が読んでいない (不要か綴り違い)")
    for name in sorted(sample - known):
        fail(f"env/mc-monitor.env_sample の {name} を monitor.py が読んでいない")


def check_server_env() -> None:
    tftpl = env_keys(read("terraform/templates/mc-server.env.tftpl"))
    sample = env_keys(read("env/mc-server.env_sample"))
    if tftpl != sample:
        fail(
            "mc-server.env.tftpl と env/mc-server.env_sample のキーが不一致: "
            f"tftpl のみ={sorted(tftpl - sample)} sample のみ={sorted(sample - tftpl)}"
        )
    compose = read("terraform/templates/docker-compose.yml.tftpl")
    # compose が $${VAR} で参照している変数は .env に必要
    for name in sorted(set(re.findall(r"\$\$\{([A-Z_][A-Z0-9_]*)\}", compose))):
        if name not in tftpl:
            fail(f"docker-compose が参照する {name} が mc-server.env.tftpl にない")


# ---------------------------------------------------------- 2. Terraform 変数

def tf_variables() -> dict[str, bool]:
    """variables.tf の変数名 → 既定値を持つか。"""
    text = read("terraform/variables.tf")
    result: dict[str, bool] = {}
    # variable "name" { ... } を雑にブロック単位で切る
    for m in re.finditer(r'^variable\s+"([^"]+)"\s*\{', text, re.MULTILINE):
        name = m.group(1)
        start = m.end()
        depth = 1
        i = start
        while i < len(text) and depth > 0:
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
            i += 1
        body = text[start : i - 1]
        result[name] = re.search(r"^\s*default\s*=", body, re.MULTILINE) is not None
    return result


def check_tfvars_sample() -> None:
    declared = tf_variables()
    sample = read("terraform/terraform.tfvars_sample")
    notes.append(f"terraform/variables.tf: 変数 {len(declared)} 個")

    # コメントアウトされた行も「載っている」とみなす (任意項目の案内として)。
    # 行頭 (インデントなし) に限定しているのは、monitor_thresholds = { cpu = ... }
    # のようなオブジェクト内のキーを変数名と誤認しないため。
    present = set(re.findall(r"^#?\s?([a-z_][a-z0-9_]*)\s*=", sample, re.MULTILINE))

    for name, has_default in sorted(declared.items()):
        if name in present:
            continue
        if has_default:
            fail(f"変数 {name} が terraform.tfvars_sample に載っていない (任意項目)")
        else:
            fail(f"必須変数 {name} が terraform.tfvars_sample に載っていない")

    for name in sorted(present - set(declared)):
        # tfvars の値に現れる語を拾ってしまった場合は無視できるよう報告のみ
        fail(f"terraform.tfvars_sample の {name} は variables.tf に宣言がない")


# ------------------------------------------------------------- 3. .gitignore

SECRET_PATHS = [
    "terraform/terraform.tfvars",
    "terraform/terraform.tfstate",
    "ansible/files/mc-monitor.env",
    "ansible/inventory.yml",
]


def check_gitignore() -> None:
    patterns = [
        line.strip()
        for line in read(".gitignore").splitlines()
        if line.strip() and not line.startswith("#")
    ]

    def ignored(path: str) -> bool:
        for p in patterns:
            body = p.lstrip("/").rstrip("/")
            if not body:
                continue
            # ** や * を正規表現に落として、パスのどの区間にも当てられるか見る
            rx = re.escape(body).replace(r"\*\*", ".*").replace(r"\*", "[^/]*")
            if re.search(rf"(^|/){rx}(/|$)", path):
                return True
        return False

    for path in SECRET_PATHS:
        if not ignored(path):
            fail(f".gitignore が {path} を無視していない (秘密がコミットされる)")


# ----------------------------------------------------------- 4. spec と wiki

def check_spec_wiki() -> None:
    spec_dir = ROOT / "docs" / "spec"
    wiki_dir = ROOT / "docs" / "wiki"
    if not spec_dir.is_dir():
        fail("docs/spec/ がない")
        return
    specs = sorted(p.name for p in spec_dir.glob("*.md") if p.name != "README.md")
    notes.append(f"docs/spec/: {len(specs)} 本")
    if not wiki_dir.is_dir():
        notes.append("docs/wiki/ は未生成 (scripts/sync-wiki.py で生成する)")
        return
    for name in specs:
        page = wiki_dir / ("Spec-" + name)
        if not page.exists():
            fail(f"docs/wiki/{page.name} がない。scripts/sync-wiki.py を実行して再生成してください")


# --------------------------------------------------- 5. requirements.txt の生成条件

# mc-monitor は Ubuntu 24.04 (Python 3.12) の x86_64。
# 手元の Python で解決すると別バージョンが選ばれるため、対象を明示して生成する。
EXPECTED_COMPILE_FLAGS = [
    "--python-version 3.12",
    "--python-platform x86_64-unknown-linux-gnu",
    "--group monitor",
]


def check_requirements_provenance() -> None:
    """requirements.txt が正しいターゲット指定で生成されているか見る。

    uv pip compile はヘッダに実行コマンドを書き残すので、それを検査する。
    指定を忘れると手元の Python 向けに解決され、VM 上で動かない組み合わせが
    ピン留めされることがある (実際に oci のバージョンが変わった)。
    """
    text = read("monitor/requirements.txt")
    header = "\n".join(text.splitlines()[:3])

    if "autogenerated by uv" not in header:
        fail(
            "monitor/requirements.txt が uv pip compile の生成物ではありません。"
            "手で編集せず pyproject.toml から生成してください"
        )
        return

    for flag in EXPECTED_COMPILE_FLAGS:
        if flag not in header:
            fail(
                f"monitor/requirements.txt の生成時に {flag} が指定されていません。"
                f"mc-monitor (Ubuntu 24.04 / x86_64) 向けに再生成してください"
            )

    # 直接依存が pyproject と requirements の両方に現れているか
    pyproject = read("pyproject.toml")
    group = pyproject.split("monitor = [")[1].split("]")[0] if "monitor = [" in pyproject else ""
    declared = set(re.findall(r'"([A-Za-z0-9_.-]+)', group))
    pinned = {m.lower() for m in re.findall(r"^([A-Za-z0-9_.-]+)==", text, re.MULTILINE)}
    for name in sorted(declared):
        if name.lower().replace("_", "-") not in pinned:
            fail(f"pyproject.toml の依存 {name} が requirements.txt にピン留めされていません")
    notes.append(f"Python 依存: 直接={len(declared)} ピン留め={len(pinned)}")


# ------------------------------------------------------------- 6. 改行コード

# VM 上で実行・解釈されるファイル。CRLF だと壊れる。
LF_REQUIRED = [
    "terraform/templates/*.tftpl",
    "terraform/cloud-init/*.tftpl",
    "monitor/monitor.py",
    "monitor/requirements.txt",
    "monitor/systemd/*",
    "scripts/*.sh",
    "ansible/*.yml",
    "ansible/ansible.cfg",
    "env/*_sample",
    "tailscale/*.hujson",
]


def check_line_endings() -> None:
    """CRLF のファイルを検出する。

    cloud-init の write_files はテンプレートの中身をそのまま VM に埋め込むため、
    手元の改行コードがそのまま本番の不具合になる。
    render.tf でも正規化しているが、混入自体をここで止める。
    """
    checked = 0
    for pattern in LF_REQUIRED:
        for path in sorted(ROOT.glob(pattern)):
            if not path.is_file():
                continue
            checked += 1
            if b"\r\n" in path.read_bytes():
                fail(
                    f"{path.relative_to(ROOT).as_posix()} が CRLF です。"
                    f"LF に直してください (.gitattributes で eol=lf を指定済み)"
                )
    notes.append(f"改行コード: {checked} ファイルを確認")


# ------------------------------------------------------------------- 実行

def main() -> int:
    for name, fn in [
        ("monitor.py の環境変数", check_monitor_env),
        ("mc-server の環境変数", check_server_env),
        ("terraform.tfvars_sample", check_tfvars_sample),
        (".gitignore", check_gitignore),
        ("docs/spec/ と docs/wiki/", check_spec_wiki),
        ("requirements.txt の生成条件", check_requirements_provenance),
        ("改行コード", check_line_endings),
    ]:
        try:
            fn()
        except FileNotFoundError as e:
            fail(f"{name}: ファイルがない: {e.filename}")

    for n in notes:
        print(f"  {n}")

    if failures:
        print(f"\nNG: {len(failures)} 件")
        for f in failures:
            print(f"  - {f}")
        return 1

    print("\nOK: 整合性の問題は見つかりませんでした")
    return 0


if __name__ == "__main__":
    sys.exit(main())
