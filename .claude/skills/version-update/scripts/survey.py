#!/usr/bin/env python3
"""リポジトリ内のピン留めを読み、upstream の最新版と突き合わせる。

    uv run .claude/skills/version-update/scripts/survey.py

標準ライブラリだけで動く (リポジトリの scripts/ と同じ方針)。
ネットワークに出られない環境では latest を "?" にして続行する。

playit-agent はタグを上げる前にエントリポイントの確認が要るので、
そこだけ専用のオプションを持たせている。

    uv run .claude/skills/version-update/scripts/survey.py --playit-entrypoint v1.0.10
"""

from __future__ import annotations

import argparse
import base64
import json
import re
import sys
import tomllib
import unicodedata
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
UA = {"User-Agent": "minecraft-oci-version-survey"}
TIMEOUT = 15

# 対象と、その最新版の取得元。
GITHUB_REPOS = {
    "Terraform": "hashicorp/terraform",
    "oracle/oci provider": "oracle/terraform-provider-oci",
    "hashicorp/local provider": "hashicorp/terraform-provider-local",
    "playit-agent": "playit-cloud/playit-agent",
    "uv": "astral-sh/uv",
    "tenv": "tofuutils/tenv",
}
PYPI_EXTRA = ["ansible-core"]

PLAYIT_REPO = "playit-cloud/playit-agent"


def get_json(url: str):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=TIMEOUT) as res:
        return json.load(res)


def latest_github(repo: str) -> str:
    """最新の安定版タグ。prerelease は除く。"""
    try:
        rels = get_json(f"https://api.github.com/repos/{repo}/releases?per_page=30")
    except (urllib.error.URLError, OSError, json.JSONDecodeError):
        return "?"
    for r in rels:
        if not r.get("prerelease") and not r.get("draft"):
            return str(r.get("tag_name", "?")).lstrip("v")
    return "?"


def latest_pypi(pkg: str) -> str:
    try:
        return str(get_json(f"https://pypi.org/pypi/{pkg}/json")["info"]["version"])
    except (urllib.error.URLError, OSError, KeyError, json.JSONDecodeError):
        return "?"


def read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


# ------------------------------------------------------------ リポジトリ側を読む


def pinned() -> dict[str, tuple[str, str]]:
    """表示名 -> (現在の値, 定義場所)"""
    out: dict[str, tuple[str, str]] = {}

    out["Terraform"] = (
        read("terraform/.terraform-version").strip(),
        "terraform/.terraform-version",
    )

    versions_tf = read("terraform/versions.tf")
    for label, source in (
        ("oracle/oci provider", "oracle/oci"),
        ("hashicorp/local provider", "hashicorp/local"),
    ):
        m = re.search(
            rf'source\s*=\s*"{re.escape(source)}"\s*\n\s*version\s*=\s*"([^"]+)"',
            versions_tf,
        )
        out[label] = (m.group(1) if m else "?", "terraform/versions.tf")

    lock = read("terraform/.terraform.lock.hcl")
    for label, source in (
        ("oracle/oci provider (lock)", "registry.terraform.io/oracle/oci"),
        ("hashicorp/local provider (lock)", "registry.terraform.io/hashicorp/local"),
    ):
        m = re.search(
            rf'provider\s+"{re.escape(source)}"\s*\{{\s*\n\s*version\s*=\s*"([^"]+)"',
            lock,
        )
        out[label] = (m.group(1) if m else "?", "terraform/.terraform.lock.hcl")

    compose = read("terraform/templates/docker-compose.yml.tftpl")
    m = re.search(r"playit-cloud/playit-agent:(\S+)", compose)
    out["playit-agent"] = (
        m.group(1) if m else "?",
        "terraform/templates/docker-compose.yml.tftpl",
    )

    return out


def python_deps() -> list[tuple[str, str, str]]:
    """(パッケージ名, pyproject の制約, requirements.txt のピン)"""
    data = tomllib.loads(read("pyproject.toml"))
    specs = data.get("dependency-groups", {}).get("monitor", [])

    reqs: dict[str, str] = {}
    for line in read("monitor/requirements.txt").splitlines():
        m = re.match(r"^([A-Za-z0-9._-]+)==(\S+)", line)
        if m:
            reqs[m.group(1).lower().replace("_", "-")] = m.group(2)

    rows = []
    for spec in specs:
        name = re.split(r"[<>=!~\[]", spec, maxsplit=1)[0].strip()
        key = name.lower().replace("_", "-")
        rows.append((name, spec[len(name) :].strip(), reqs.get(key, "-")))
    return rows, reqs


# ------------------------------------------------------------ 比較


def parse(v: str) -> tuple[int, ...]:
    return tuple(int(x) for x in re.findall(r"\d+", v)[:4]) or (0,)


def verdict(current: str, latest: str) -> str:
    if latest == "?" or current == "?":
        return "-"
    if parse(current) == parse(latest):
        return "最新"
    if parse(current) < parse(latest):
        return "更新あり"
    return "手元が先行"


def satisfies_pessimistic(constraint: str, version: str) -> bool | None:
    """`~> X.Y` に version が収まるか。判定できなければ None。"""
    m = re.match(r"^~>\s*(\d+)\.(\d+)$", constraint.strip())
    if not m:
        return None
    major, minor = int(m.group(1)), int(m.group(2))
    v = parse(version)
    if len(v) < 2:
        return None
    return v[0] == major and v[1] >= minor


# ------------------------------------------------------------ playit


def playit_entrypoint(ref: str) -> None:
    """指定タグの docker/entrypoint.sh を出す。

    タグを上げる前にこれを読む。秘密鍵を受け取る環境変数名が変わっていると、
    .env とドキュメントまで巻き込んだ修正になる。
    """
    for path in ("docker/entrypoint.sh", "Dockerfile"):
        print(f"===== {path} @ {ref} =====")
        try:
            c = get_json(
                f"https://api.github.com/repos/{PLAYIT_REPO}/contents/{path}?ref={ref}"
            )
            print(base64.b64decode(c["content"]).decode("utf-8"))
        except (urllib.error.URLError, OSError, KeyError, json.JSONDecodeError) as e:
            print(f"  取得できなかった: {e}")


def playit_tags() -> None:
    try:
        tags = get_json(f"https://api.github.com/repos/{PLAYIT_REPO}/tags?per_page=100")
    except (urllib.error.URLError, OSError, json.JSONDecodeError):
        print("  タグ一覧を取得できなかった")
        return
    stable = [t["name"] for t in tags if re.fullmatch(r"v\d+\.\d+(\.\d+)?", t["name"])]
    print("  安定版タグ (新しい順): " + ", ".join(stable[:12]))


# ------------------------------------------------------------ 出力


def width(s: str) -> int:
    """全角を 2 で数える。日本語の列が混ざると str.ljust では揃わない。"""
    return sum(2 if unicodedata.east_asian_width(c) in "WF" else 1 for c in s)


def table(rows: list[list[str]], headers: list[str]) -> None:
    widths = [max(width(r[i]) for r in [headers, *rows]) for i in range(len(headers))]

    def pad(cells: list[str]) -> str:
        return "  ".join(c + " " * (widths[i] - width(c)) for i, c in enumerate(cells))

    print(pad(headers))
    print("  ".join("-" * w for w in widths))
    for r in rows:
        print(pad(r))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--playit-entrypoint",
        metavar="TAG",
        help="指定タグの playit-agent エントリポイントを出して終了する (例: v1.0.10)",
    )
    ap.add_argument("--offline", action="store_true", help="upstream を見に行かない")
    args = ap.parse_args()

    if args.playit_entrypoint:
        playit_entrypoint(args.playit_entrypoint)
        return 0

    pins = pinned()
    deps, reqs = python_deps()

    def latest_gh(label: str) -> str:
        return "?" if args.offline else latest_github(GITHUB_REPOS[label])

    print("## 固定しているもの\n")
    rows = []
    for label in ("Terraform", "oracle/oci provider", "hashicorp/local provider"):
        cur, where = pins[label]
        lock = pins.get(f"{label} (lock)", ("-", ""))[0]
        latest = latest_gh(label)
        shown = cur if lock == "-" else f"{cur} (lock {lock})"
        note = verdict(lock if lock != "-" else cur, latest)
        if lock != "-":
            ok = satisfies_pessimistic(cur, latest)
            if ok is False:
                note += " / 制約外 (制約も上げる必要あり)"
        rows.append([label, shown, latest, note, where])

    cur, where = pins["playit-agent"]
    rows.append(
        ["playit-agent", cur, latest_gh("playit-agent"), verdict(cur, latest_gh("playit-agent")), where]
    )
    table(rows, ["対象", "現在", "最新", "判定", "定義場所"])

    print("\n## Python 直接依存 (pyproject.toml の monitor グループ)\n")
    rows = []
    for name, constraint, pin in deps:
        latest = "?" if args.offline else latest_pypi(name)
        rows.append([name, constraint, pin, latest, verdict(pin, latest)])
    table(rows, ["パッケージ", "制約", "requirements.txt", "最新", "判定"])

    print("\n## 推移的依存で古くなっているもの\n")
    direct = {re.split(r"[<>=!~\[]", s[0], maxsplit=1)[0].lower() for s in deps}
    rows = []
    for name, pin in sorted(reqs.items()):
        if name in direct:
            continue
        latest = "?" if args.offline else latest_pypi(name)
        v = verdict(pin, latest)
        if v == "更新あり":
            rows.append([name, pin, latest])
    if rows:
        table(rows, ["パッケージ", "requirements.txt", "最新"])
        print("\n  → 直接依存を上げて uv pip compile で再生成する (手編集しない)")
    else:
        print("  なし")

    print("\n## 手元のツール\n")
    rows = []
    for label in ("uv", "tenv"):
        rows.append([label, latest_gh(label)])
    for pkg in PYPI_EXTRA:
        rows.append([pkg, "?" if args.offline else latest_pypi(pkg)])
    table(rows, ["対象", "最新"])
    print("\n  手元の版は uv --version / tenv --version / ansible --version で確認する")

    print("\n## playit-agent\n")
    if not args.offline:
        playit_tags()
    print("  タグを上げる前に --playit-entrypoint <tag> で環境変数名を確認すること")

    return 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
