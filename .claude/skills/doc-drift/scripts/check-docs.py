#!/usr/bin/env python3
"""ドキュメントの記述が実装と食い違っていないかを検査する。

    uv run .claude/skills/doc-drift/scripts/check-docs.py
    ... --facts    実装から取れる事実だけを一覧で出す (機械検査できない記述を人が読むため)

標準ライブラリだけで動く (リポジトリの scripts/ と同じ方針)。コードが常に正。

scripts/check-consistency.py が「コードと設定ファイルの間」を見るのに対し、
こちらは「ドキュメントとコードの間」を見る。機械で判定できるのは

  - 参照 (リンク・ファイルパス・変数名・出力名・Ansible タグ) が実在するか
  - 表に書かれた値 (既定値・sensitive・環境変数名) がコードと一致するか
  - 文章に埋め込まれた固定値 (バージョン・ポート・IP・間隔) がコードと一致するか

までで、説明が妥当かどうかは読まないと分からない。--facts はそのための材料。
"""

from __future__ import annotations

import argparse
import ast
import re
import subprocess
import sys
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]

# 検査対象。docs/wiki/ は生成物だが、手書きの Home.md / Runbook-Index.md / _Footer.md が
# 混ざっているうえ、リンクの書式が spec と違うので同じように見る。
DOC_GLOBS = ["docs/**/*.md", "README.md", "CLAUDE.md", "ansible/README.md"]

# リポジトリ内のパスとして扱う先頭要素。これ以外で始まる絶対パス (/home/ubuntu/...) や
# ~ 始まりは VM 上・利用者の手元のパスなので対象外。
REPO_TOPS = (
    "terraform/", "monitor/", "ansible/", "scripts/", "docs/", "env/",
    "dashboards/", "tailscale/", ".vscode/", ".claude/", ".github/",
)

findings: list[tuple[str, str, str, str]] = []  # (level, category, where, message)


def add(level: str, category: str, where: str, message: str) -> None:
    findings.append((level, category, where, message))


def read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


@dataclass
class Doc:
    rel: str
    text: str

    @property
    def is_wiki(self) -> bool:
        return self.rel.startswith("docs/wiki/")

    @property
    def is_manual(self) -> bool:
        return self.rel.startswith("docs/manual/")


def load_docs() -> list[Doc]:
    docs: list[Doc] = []
    seen: set[str] = set()
    for pattern in DOC_GLOBS:
        for p in sorted(ROOT.glob(pattern)):
            rel = p.relative_to(ROOT).as_posix()
            if rel in seen or not p.is_file():
                continue
            seen.add(rel)
            docs.append(Doc(rel, p.read_text(encoding="utf-8")))
    return docs


# ------------------------------------------------------------ 実装から事実を取る

@dataclass
class Impl:
    """コード側から読み取った事実。すべてファイルから取る (この中に定数を書かない)。"""

    variables: dict[str, dict] = field(default_factory=dict)
    outputs: set[str] = field(default_factory=set)
    monitor_required: set[str] = field(default_factory=set)
    monitor_optional: set[str] = field(default_factory=set)
    env_keys: dict[str, set[str]] = field(default_factory=dict)
    ansible_tags: set[str] = field(default_factory=set)
    exposure_modes: set[str] = field(default_factory=set)
    plugins: dict[str, str] = field(default_factory=dict)  # ID -> プラグイン名
    scalars: dict[str, str] = field(default_factory=dict)  # 表示用の雑多な固定値


def block_of(text: str, start: int) -> str:
    """`{` の直後から対応する `}` の手前までを返す。"""
    depth, i = 1, start
    while i < len(text) and depth > 0:
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
        i += 1
    return text[start : i - 1]


def hcl_default(block: str) -> str | None:
    """variable ブロックから default の値を生のまま取る (複数行のリスト/オブジェクト対応)。

    行末コメント (`default = ["8631", "28140"] # CoreProtect, LuckPerms`) は落とす。
    """
    m = re.search(r"^\s*default\s*=\s*", block, re.MULTILINE)
    if not m:
        return None
    rest = block[m.end() :]
    depth, in_str, out = 0, False, []
    for ch in rest:
        if in_str:
            out.append(ch)
            if ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch in "[{(":
            depth += 1
        elif ch in "]})":
            depth -= 1
        elif ch == "#" and depth == 0:
            break
        elif ch == "\n" and depth == 0:
            break
        out.append(ch)
    return "".join(out).strip()


def collect_impl() -> Impl:
    impl = Impl()

    # ---- Terraform 変数
    vtext = read("terraform/variables.tf")
    for m in re.finditer(r'^variable\s+"([^"]+)"\s*\{', vtext, re.MULTILINE):
        block = block_of(vtext, m.end())
        impl.variables[m.group(1)] = {
            "default": hcl_default(block),
            "sensitive": re.search(r"^\s*sensitive\s*=\s*true", block, re.MULTILINE) is not None,
            "block": block,
        }

    # exposure_mode の許容値は validation の contains() が正
    ex = impl.variables.get("exposure_mode", {}).get("block", "")
    m = re.search(r"contains\(\[([^\]]+)\]", ex)
    if m:
        impl.exposure_modes = set(re.findall(r'"([^"]+)"', m.group(1)))

    # プラグインID → 名前。variables.tf の default 行のコメントが対応表。
    mc = impl.variables.get("mc_plugins", {})
    m = re.search(r"default\s*=\s*\[([^\]]*)\]\s*#\s*(.+)", mc.get("block", ""))
    if m:
        ids = re.findall(r'"(\d+)"', m.group(1))
        names = [n.strip() for n in m.group(2).split(",")]
        if len(ids) == len(names):
            impl.plugins = dict(zip(ids, names))

    # ---- Terraform 出力
    impl.outputs = set(re.findall(r'^output\s+"([^"]+)"', read("terraform/outputs.tf"), re.MULTILINE))

    # ---- monitor.py の環境変数
    tree = ast.parse(read("monitor/monitor.py"))
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Subscript)
            and isinstance(node.value, ast.Attribute)
            and node.value.attr == "environ"
            and isinstance(node.slice, ast.Constant)
            and isinstance(node.slice.value, str)
        ):
            impl.monitor_required.add(node.slice.value)
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "get"
            and isinstance(node.func.value, ast.Attribute)
            and node.func.value.attr == "environ"
            and node.args
            and isinstance(node.args[0], ast.Constant)
        ):
            impl.monitor_optional.add(node.args[0].value)

    # ---- .env テンプレートのキー
    for label, rel in (
        ("mc-server", "terraform/templates/mc-server.env.tftpl"),
        ("mc-monitor", "terraform/templates/mc-monitor.env.tftpl"),
    ):
        impl.env_keys[label] = {
            m.group(1)
            for line in read(rel).splitlines()
            if (m := re.match(r"^([A-Z_][A-Z0-9_]*)=", line.strip()))
        }

    # ---- Ansible のタグ
    impl.ansible_tags = set(re.findall(r"^\s*tags:\s*\[([^\]]+)\]", read("ansible/site.yml"), re.MULTILINE))
    impl.ansible_tags = {t.strip() for group in impl.ansible_tags for t in group.split(",")}

    # ---- 固定値
    compute = read("terraform/compute.tf")
    compose = read("terraform/templates/docker-compose.yml.tftpl")
    timer = read("monitor/systemd/mc-monitor.timer")

    def first(rx: str, text: str, default: str = "?") -> str:
        m = re.search(rx, text)
        return m.group(1) if m else default

    impl.scalars = {
        "terraform_version": read("terraform/.terraform-version").strip(),
        "required_version": first(r'required_version\s*=\s*"([^"]+)"', read("terraform/versions.tf")),
        "playit_tag": first(r"playit-cloud/playit-agent:(\S+)", compose),
        "ocpus": first(r"ocpus\s*=\s*(\d+)", compute),
        "memory_gb": first(r"memory_in_gbs\s*=\s*(\d+)", compute),
        "boot_mc": first(r"boot_volume_size_in_gbs\s*=\s*(\d+)", compute),
        "boot_monitor": (re.findall(r"boot_volume_size_in_gbs\s*=\s*(\d+)", compute) + ["?", "?"])[1],
        "shape_mc": first(r'display_name\s*=\s*"mc-server"\s*\n\s*shape\s*=\s*"([^"]+)"', compute),
        "shape_monitor": first(r'display_name\s*=\s*"mc-monitor"\s*\n\s*shape\s*=\s*"([^"]+)"', compute),
        "ubuntu": first(r'operating_system_version\s*=\s*"([^"]+)"', compute),
        "monitor_interval": first(r"OnUnitActiveSec=(\d+min)", timer),
        "monitor_boot_delay": first(r"OnBootSec=(\d+min)", timer),
        "mc_type": first(r"TYPE:\s*\"?([A-Z]+)", compose),
        "mc_version": first(r"VERSION:\s*\"?([A-Z]+)", compose),
    }
    return impl


# ------------------------------------------------------------ 1. 参照の実在

MD_LINK = re.compile(r"\[([^\]]*)\]\(([^)\s]+)\)")


def check_links(docs: list[Doc]) -> None:
    cat = "リンク"
    # .gitignore 済みのファイル (todo.md など) は、リポジトリに無いのが正常。
    # check_paths と同じ扱いにする。
    targets: list[str] = []
    for doc in docs:
        base = (ROOT / doc.rel).parent
        for m in MD_LINK.finditer(doc.text):
            t = m.group(2).split("#", 1)[0]
            if not t or t.startswith(("http://", "https://", "mailto:")):
                continue
            if doc.is_wiki:
                if t.startswith("../blob/main/"):
                    targets.append(t[len("../blob/main/") :])
                continue
            resolved = (base / t).resolve()
            if not resolved.exists():
                try:
                    targets.append(resolved.relative_to(ROOT.resolve()).as_posix())
                except ValueError:
                    pass
    ignored = gitignored(sorted(set(targets)))

    for doc in docs:
        base = (ROOT / doc.rel).parent
        for m in MD_LINK.finditer(doc.text):
            target = m.group(2).split("#", 1)[0]
            if not target or target.startswith(("http://", "https://", "mailto:")):
                continue

            if doc.is_wiki:
                # wiki は [x](Spec-08-parameters) と [x](../blob/main/terraform/x.tf) の 2 形式
                if target.startswith("../blob/main/"):
                    rel = target[len("../blob/main/") :]
                    if not (ROOT / rel).exists() and rel not in ignored:
                        add("NG", cat, doc.rel, f"リポジトリ上に存在しないパスへのリンク: {rel}")
                elif re.fullmatch(r"[\w.-]+", target) and not target.endswith(".md"):
                    if not (ROOT / "docs" / "wiki" / f"{target}.md").exists():
                        add("NG", cat, doc.rel, f"wiki に存在しないページへのリンク: {target}")
                continue

            resolved = (base / target).resolve()
            if resolved.exists():
                continue
            try:
                rel = resolved.relative_to(ROOT.resolve()).as_posix()
            except ValueError:
                rel = ""
            if rel and rel in ignored:
                continue
            add("NG", cat, doc.rel, f"リンク先がない: {target}")


def gitignored(paths: list[str]) -> set[str]:
    """.gitignore で無視されるパスを返す。

    terraform.tfvars / ansible/files/ / ansible/inventory.yml は「利用者が作る」
    「apply が生成する」ファイルで、リポジトリに無いのが正常。文書が参照していても
    不在を責められない。無視対象かどうかは .gitignore が唯一の正なので git に聞く。
    """
    if not paths:
        return set()
    # -z (NUL 区切り) でやり取りする。text=True の stdin は Windows で \n が \r\n に
    # 変換され、パス末尾の \r のせいで一致しなくなる。出力側の quote も避けられる。
    try:
        p = subprocess.run(
            ["git", "check-ignore", "-z", "--stdin"],
            cwd=ROOT, input="\0".join(paths).encode("utf-8"),
            capture_output=True, timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        return set()
    return {
        s.decode("utf-8", "replace").replace("\\", "/").rstrip("/")
        for s in p.stdout.split(b"\0")
        if s
    }


def check_paths(docs: list[Doc], impl: Impl) -> None:
    """バッククォート内・コードブロック内で言及されたリポジトリ相対パスの実在。"""
    cat = "ファイル参照"
    rx = re.compile(r"(?<![\w./-])((?:" + "|".join(re.escape(t) for t in REPO_TOPS) + r")[\w./*{}-]+)")

    # (doc, path) を集めてから、.gitignore 対象をまとめて除外する
    candidates: list[tuple[Doc, str]] = []
    globs: list[tuple[Doc, str]] = []
    for doc in docs:
        seen: set[str] = set()
        for m in rx.finditer(doc.text):
            raw = m.group(1).rstrip(".,)」）:；;")
            if raw in seen or raw.endswith("/"):
                continue
            seen.add(raw)
            if "*" in raw or "{" in raw:
                globs.append((doc, raw))
            # 拡張子のない `tailscale/zerotier` のような表記は地の文のことがある
            # (「mc-router を tailscale/zerotier に広げない」)。ファイル名と区別できないので見ない。
            elif re.search(r"\.[A-Za-z0-9_]{1,10}$", raw.rsplit("/", 1)[-1]):
                candidates.append((doc, raw))

    # ディレクトリの .gitignore 記法 (`ansible/files/`) は、実体がないと末尾 / なしでは
    # 一致しない。glob の親は両方の形で聞く。
    asked = {p for _, p in candidates}
    for _, raw in globs:
        parent = raw.split("*")[0].rstrip("/")
        asked |= {parent, parent + "/"}
    ignored = gitignored(sorted(asked))

    for doc, raw in candidates:
        if (ROOT / raw).exists() or raw in ignored:
            continue
        add("警告" if doc.is_manual else "NG", cat, doc.rel, f"存在しないパスを参照している: {raw}")

    for doc, raw in globs:
        if list(ROOT.glob(raw)) or raw.split("*")[0].rstrip("/") in ignored:
            continue
        add("警告", cat, doc.rel, f"パターンに一致するファイルがない: {raw}")


def check_names(docs: list[Doc], impl: Impl) -> None:
    """var.xxx / terraform output xxx / -t タグ / exposure_mode の値。"""
    for doc in docs:
        for name in sorted(set(re.findall(r"\bvar\.([a-z_][a-z0-9_]*)", doc.text))):
            if name not in impl.variables:
                add("NG", "変数名", doc.rel, f"var.{name} は variables.tf に宣言がない")

        for name in sorted(set(re.findall(r"terraform output (?:-raw )?([a-z_][a-z0-9_]*)", doc.text))):
            if name not in impl.outputs:
                add("NG", "出力名", doc.rel, f"terraform output {name} は outputs.tf にない")

        for tag in sorted(set(re.findall(r"site\.yml[^\n`]*?-t\s+([a-z-]+)", doc.text))):
            if tag not in impl.ansible_tags:
                add(
                    "NG",
                    "Ansible タグ",
                    doc.rel,
                    f"site.yml -t {tag} というタグは site.yml にない (あるのは {sorted(impl.ansible_tags)})",
                )

        if impl.exposure_modes:
            for mode in sorted(set(re.findall(r'exposure_mode\s*=\s*"([a-z]+)"', doc.text))):
                if mode not in impl.exposure_modes:
                    add(
                        "NG",
                        "変数の値",
                        doc.rel,
                        f'exposure_mode = "{mode}" は validation の許容値 {sorted(impl.exposure_modes)} にない',
                    )


# ------------------------------------------------------------ 2. 表と実装

def table_rows(text: str) -> list[list[str]]:
    rows = []
    for line in text.splitlines():
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) >= 2 and not re.fullmatch(r"-{2,}", cells[0].replace(" ", "")):
            rows.append(cells)
    return rows


def norm(value: str) -> str:
    """表に書かれた既定値と HCL の既定値を比べられる形に均す。"""
    v = value.strip().strip("`").strip()
    v = v.replace("**", "").strip()
    if v in ('""', "''"):
        return ""
    if v.startswith('"') and v.endswith('"') and len(v) >= 2:
        v = v[1:-1]
    return re.sub(r"[\s'\"]", "", v)


# 既定値をそのまま表に書けないもの (オブジェクト型など) は突き合わせない。
DEFAULT_COMPARE_SKIP = {"monitor_thresholds"}


def check_parameter_table(impl: Impl) -> None:
    cat = "パラメータ表"
    rel = "docs/spec/08-parameters.md"
    text = read(rel)
    head, _, tail = text.partition("## `.env` として VM に配置される変数")

    documented: dict[str, list[str]] = {}
    for cells in table_rows(head):
        m = re.fullmatch(r"`([a-z_][a-z0-9_]*)`", cells[0])
        if m and len(cells) >= 3:
            documented[m.group(1)] = cells

    for name in sorted(set(impl.variables) - set(documented)):
        add("NG", cat, rel, f"変数 {name} が表に載っていない")
    for name in sorted(set(documented) - set(impl.variables)):
        add("NG", cat, rel, f"表の {name} は variables.tf に宣言がない")

    for name, cells in sorted(documented.items()):
        if name not in impl.variables:
            continue
        impl_default = impl.variables[name]["default"]
        doc_default = cells[1]

        if name not in DEFAULT_COMPARE_SKIP:
            if impl_default is None:
                if "必須" not in doc_default:
                    add("NG", cat, rel, f"{name} は既定値がないのに表は「{doc_default}」")
            elif "必須" in doc_default:
                add("NG", cat, rel, f"{name} の既定値は {impl_default} だが表は「必須」")
            elif norm(doc_default) != norm(impl_default):
                add("NG", cat, rel, f"{name} の既定値: 表「{doc_default}」 / 実装 {impl_default}")

        doc_secret = "秘" in cells[2]
        if doc_secret != impl.variables[name]["sensitive"]:
            add(
                "NG",
                cat,
                rel,
                f"{name} の sensitive: 表「{'秘' if doc_secret else '空欄'}」 / "
                f"実装 {impl.variables[name]['sensitive']}",
            )

    # Terraform 出力の表
    out_section = tail.partition("## Terraform 出力")[2].partition("##")[0]
    doc_outputs = set()
    for cells in table_rows(out_section):
        for token in re.findall(r"`([a-z_][a-z0-9_]*)`", cells[0]):
            doc_outputs.add(token)
    for name in sorted(impl.outputs - doc_outputs):
        add("NG", cat, rel, f"出力 {name} が「Terraform 出力」の表にない")
    for name in sorted(doc_outputs - impl.outputs):
        add("NG", cat, rel, f"表の出力 {name} は outputs.tf にない")

    # .env の表
    env_section = tail.partition("## Terraform 出力")[0]
    for label, marker in (("mc-server", "### mc-server:"), ("mc-monitor", "### mc-monitor:")):
        part = env_section.partition(marker)[2].partition("###")[0]
        if not part:
            continue
        # 表の1列目だけを見る。地の文にも環境変数名が出てくる
        # (「monitor.py はこれ以外に STATE_FILE も任意で受け付ける」など)。
        doc_keys: set[str] = set()
        for cells in table_rows(part):
            doc_keys |= expand_env_tokens(re.findall(r"`([A-Z_][A-Z0-9_]*)`", cells[0]))
        for key in sorted(impl.env_keys[label] - doc_keys):
            add("NG", cat, rel, f"{label} の .env の {key} が表にない")
        for key in sorted(doc_keys - impl.env_keys[label]):
            add("NG", cat, rel, f"{label} の表にある {key} をテンプレートが生成していない")


def expand_env_tokens(tokens: list[str]) -> set[str]:
    """`THRESHOLD_CPU` / `_MEMORY` のような省略記法を直前の接頭辞で補う。"""
    out: set[str] = set()
    prefix = ""
    for t in tokens:
        if t.startswith("_") and prefix:
            out.add(prefix + t)
            continue
        out.add(t)
        prefix = t.split("_")[0]
    return out


def check_env_samples(impl: Impl) -> None:
    """env/*_sample の値が Terraform の既定値と食い違っていないか。

    サンプルは「Terraform を使わずに手で置く場合の雛形」なので、既定値とずれると
    そのまま嘘になる。
    """
    cat = "env サンプル"
    rel = "env/mc-monitor.env_sample"
    values = {}
    for line in read(rel).splitlines():
        m = re.match(r"^([A-Z_][A-Z0-9_]*)=(.*)$", line.strip())
        if m:
            values[m.group(1)] = m.group(2).strip()

    def default_of(var: str) -> str | None:
        d = impl.variables.get(var, {}).get("default")
        return None if d is None else norm(d)

    expect = {
        "RCON_HOST": default_of("mc_private_ip"),
        "FILESYSTEM_NAME": default_of("filesystem_name"),
    }
    thresholds = impl.variables.get("monitor_thresholds", {}).get("default", "")
    for key, var in (("CPU", "cpu"), ("MEMORY", "memory"), ("DISK", "disk"), ("TPS", "tps")):
        m = re.search(rf"^\s*{var}\s*=\s*([\d.]+)", thresholds, re.MULTILINE)
        if m:
            expect[f"THRESHOLD_{key}"] = m.group(1)

    for key, want in expect.items():
        if want is None or key not in values:
            continue
        if float_eq(values[key], want):
            continue
        add("NG", cat, rel, f"{key}={values[key]} だが Terraform の既定値は {want}")


def float_eq(a: str, b: str) -> bool:
    try:
        return float(a) == float(b)
    except ValueError:
        return a == b


# ------------------------------------------------------------ 3. 文章中の固定値

def check_scalars(docs: list[Doc], impl: Impl) -> None:
    cat = "固定値"
    s = impl.scalars

    # (説明, 期待値, パターン) — パターンの group(1) が文書側の値
    singles: list[tuple[str, str, str]] = [
        ("Terraform の版", s["terraform_version"], r"terraform -version[^\n]*?(\d+\.\d+\.\d+)"),
        ("Terraform の版", s["terraform_version"], r"\.terraform-version[^\n]{0,40}?`(\d+\.\d+\.\d+)`"),
        ("Terraform の版", s["terraform_version"], r"Terraform のバージョン `(\d+\.\d+\.\d+)`"),
        ("playit-agent のタグ", s["playit_tag"], r"playit-cloud/playit-agent:(\S+?)[\s`|)]"),
        ("監視間隔", s["monitor_interval"], r"OnUnitActiveSec=(\d+min)"),
        ("監視間隔", s["monitor_interval"].replace("min", ""), r"監視間隔[^\n]{0,4}?(\d+)\s*分"),
        # 散文の「5分ごと」は見ない。同じ表現を playit-check.sh の cron (10分ごと) も使っており、
        # 文脈なしに区別できない。unit ファイルの記法と「監視間隔 N 分」だけを見る。
        ("初回実行までの待ち", s["monitor_boot_delay"], r"OnBootSec=(\d+min)"),
        ("Ubuntu の版", s["ubuntu"], r"Ubuntu (\d+\.\d+)"),
        ("mc-server の shape", s["shape_mc"], r"(VM\.Standard\.A1\.Flex)"),
        ("mc-monitor の shape", s["shape_monitor"], r"(VM\.Standard\.E2\.1\.Micro)"),
        ("Minecraft の種別", s["mc_type"], r"TYPE=([A-Z]+)"),
        ("Minecraft の版", s["mc_version"], r"VERSION=([A-Z]+)"),
    ]
    pairs: list[tuple[str, tuple[str, str], str]] = [
        ("OCPU/メモリ", (s["ocpus"], s["memory_gb"]), r"OCPU/メモリ\s*\((\d+)/(\d+)\)"),
        ("ブートボリューム", (s["boot_mc"], s["boot_monitor"]), r"ブートボリューム\s*(\d+)GB\s*/\s*(\d+)GB"),
    ]

    for doc in docs:
        for label, want, rx in singles:
            for m in re.finditer(rx, doc.text):
                # `playit-agent:<tag>` のような「値を書かない」表記は意図的なもの
                if "<" in m.group(1) or "{" in m.group(1):
                    continue
                if m.group(1) != want:
                    add("NG", cat, doc.rel, f"{label}: 文書「{m.group(1)}」 / 実装 {want}")
        for label, want2, rx in pairs:
            for m in re.finditer(rx, doc.text):
                if (m.group(1), m.group(2)) != want2:
                    add(
                        "NG",
                        cat,
                        doc.rel,
                        f"{label}: 文書「{m.group(1)}/{m.group(2)}」 / 実装 {want2[0]}/{want2[1]}",
                    )

        # プラグインID (variables.tf の default 行のコメントが対応表)
        for pid, name in impl.plugins.items():
            for m in re.finditer(rf"{re.escape(name)}\D{{0,4}}?(\d{{4,6}})", doc.text):
                if m.group(1) != pid:
                    add("NG", cat, doc.rel, f"{name} のリソースID: 文書「{m.group(1)}」 / 実装 {pid}")

    check_private_ips(docs, impl)


def check_private_ips(docs: list[Doc], impl: Impl) -> None:
    """VCN 内のアドレスは variables.tf の既定値が正。"""
    allowed = {
        norm(impl.variables[v]["default"])
        for v in ("vcn_cidr", "subnet_cidr", "mc_private_ip", "monitor_private_ip")
        if impl.variables.get(v, {}).get("default")
    }
    bases = {a.split("/")[0] for a in allowed}
    for doc in docs:
        for m in re.finditer(r"\b(10\.0\.\d+\.\d+)(/\d+)?\b", doc.text):
            whole = m.group(0)
            if whole in allowed or m.group(1) in bases:
                continue
            add(
                "警告",
                "固定値",
                doc.rel,
                f"VCN 内のアドレス {whole} が variables.tf の既定値 {sorted(allowed)} にない",
            )


def check_embedded_code(docs: list[Doc], impl: Impl) -> None:
    """文書に貼られた monitor.py のコード片が実装とずれていないか。"""
    cat = "貼り付けコード"
    known = impl.monitor_required | impl.monitor_optional
    for doc in docs:
        for block in re.findall(r"```(?:python|py)?\n(.*?)```", doc.text, re.DOTALL):
            if "os.environ" not in block:
                continue
            for name in sorted(set(re.findall(r'os\.environ\["([A-Z_][A-Z0-9_]*)"\]', block))):
                if name not in known:
                    add("NG", cat, doc.rel, f"貼り付けたコードの os.environ[{name!r}] を monitor.py は読んでいない")
                elif name in impl.monitor_optional and name not in impl.monitor_required:
                    add(
                        "警告",
                        cat,
                        doc.rel,
                        f"貼り付けたコードは {name} を必須 (os.environ[...]) にしているが、"
                        f"monitor.py は既定値つきの .get で読んでいる",
                    )


# ------------------------------------------------------------ 出力

def width(s: str) -> int:
    return sum(2 if unicodedata.east_asian_width(c) in "WF" else 1 for c in s)


def wrap(msg: str, indent: int, limit: int = 110) -> list[str]:
    lines: list[str] = []
    buf: list[str] = []
    n = 0
    for ch in msg:
        w = 2 if unicodedata.east_asian_width(ch) in "WF" else 1
        if n + w > limit - indent:
            cut = next((i for i in range(len(buf) - 1, max(len(buf) - 30, 0), -1) if buf[i] == " "), None)
            if cut is None:
                lines.append("".join(buf))
                buf = []
            else:
                lines.append("".join(buf[:cut]))
                buf = buf[cut + 1 :]
            n = sum(2 if unicodedata.east_asian_width(c) in "WF" else 1 for c in buf)
        buf.append(ch)
        n += w
    lines.append("".join(buf))
    return [lines[0]] + [" " * indent + x for x in lines[1:]]


def print_facts(impl: Impl) -> None:
    print("## 実装から取れる事実 (文書の記述と突き合わせる材料)\n")
    for key, value in impl.scalars.items():
        print(f"  {key:22} {value}")
    print(f"\n  変数            {len(impl.variables)} 個")
    print(f"  出力            {len(impl.outputs)} 個: {', '.join(sorted(impl.outputs))}")
    print(f"  Ansible タグ    {', '.join(sorted(impl.ansible_tags))}")
    print(f"  exposure_mode   {', '.join(sorted(impl.exposure_modes))}")
    print(f"  プラグイン      {', '.join(f'{k}={v}' for k, v in impl.plugins.items())}")
    print(f"  monitor 必須    {', '.join(sorted(impl.monitor_required))}")
    print(f"  monitor 任意    {', '.join(sorted(impl.monitor_optional))}")
    for label, keys in impl.env_keys.items():
        print(f"  .env {label:10} {', '.join(sorted(keys))}")
    print("\n  これらが文書の説明と合っているかは、数値の一致だけでは決まらない。")
    print("  「なぜその値なのか」の説明が古くなっていないかは本文を読んで判断する。")


def report() -> int:
    if not findings:
        print("OK: ドキュメントと実装の食い違いは見つかりませんでした")
        return 0

    order = {"NG": 0, "警告": 1, "情報": 2}
    by_cat: dict[str, list[tuple[str, str, str]]] = {}
    for level, cat, where, msg in findings:
        by_cat.setdefault(cat, []).append((level, where, msg))

    for cat in sorted(by_cat, key=lambda c: min(order[f[0]] for f in by_cat[c])):
        print(f"\n== {cat} ==")
        for level, where, msg in sorted(by_cat[cat], key=lambda f: (order[f[0]], f[1])):
            head = f"  {level}" + " " * (5 - width(level))
            body = f"{where}: {msg}"
            for i, line in enumerate(wrap(body, width(head))):
                print(head + line if i == 0 else line)

    ng = sum(1 for f in findings if f[0] == "NG")
    warn = sum(1 for f in findings if f[0] == "警告")
    print(f"\nNG {ng} 件 / 警告 {warn} 件")
    if ng:
        print("コードが正。docs/spec/ を直したら `uv run scripts/sync-wiki.py` を実行する")
    return 1 if ng else 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--facts", action="store_true", help="実装から取れる事実を一覧で出して終了する")
    args = ap.parse_args()

    impl = collect_impl()
    if args.facts:
        print_facts(impl)
        return 0

    docs = load_docs()
    print(f"検査対象: {len(docs)} ファイル")
    check_links(docs)
    check_paths(docs, impl)
    check_names(docs, impl)
    check_parameter_table(impl)
    check_env_samples(impl)
    check_scalars(docs, impl)
    check_embedded_code(docs, impl)
    return report()


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
