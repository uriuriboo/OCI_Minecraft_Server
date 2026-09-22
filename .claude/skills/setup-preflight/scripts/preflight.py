#!/usr/bin/env python3
"""構築に必要な値が手元に揃っているかを、クラウドに繋がずに検査する。

    uv run .claude/skills/setup-preflight/scripts/preflight.py
    ... --online    自宅グローバルIPを取得して home_ip_cidr と照合する
    ... --day2      Ansible 側 (inventory.yml / ansible/files/) も見る

標準ライブラリだけで動く (リポジトリの scripts/ と同じ方針)。

scripts/check-consistency.py が「リポジトリの中が食い違っていないか」を見るのに対し、
こちらは「利用者の terraform.tfvars と手元の環境に値が入っているか」を見る。
`terraform validate` は値を見ないので (未設定でも exit 0)、apply するまで気づけない。
tfvars の綴り違いに至っては警告止まりで、既定値のある変数なら黙って無視される。

秘密の値は表示しない。設定の有無と長さ、判定結果だけを出す。
"""

from __future__ import annotations

import argparse
import configparser
import difflib
import os
import re
import shutil
import subprocess
import sys
import unicodedata
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]

# 出力の節。この順で出す。
SECTIONS = [
    "手元のツール",
    "OCI 認証",
    "入力ファイル",
    "変数の充足",
    "値の形",
    "組み合わせ・運用上の前提",
    "SSH 鍵",
    "Ansible (day-2)",
]

LEVEL_ORDER = {"NG": 0, "警告": 1, "情報": 2, "OK": 3}
results: list[tuple[str, str, str]] = []


def add(level: str, section: str, msg: str) -> None:
    results.append((level, section, msg))


def read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


# ------------------------------------------------------------ HCL を読む

@dataclass
class Value:
    """tfvars の 1 代入。型は raw から必要なときだけ解釈する。"""

    name: str
    raw: str
    source: str

    @property
    def is_string(self) -> bool:
        return self.raw.startswith('"') and self.raw.endswith('"') and len(self.raw) >= 2

    def as_string(self) -> str | None:
        if not self.is_string:
            return None
        body = self.raw[1:-1]
        return body.replace('\\"', '"').replace("\\\\", "\\")

    def as_bool(self) -> bool | None:
        return {"true": True, "false": False}.get(self.raw.strip())

    def as_number(self) -> float | None:
        try:
            return float(self.raw.strip())
        except ValueError:
            return None

    def as_list(self) -> list[str] | None:
        raw = self.raw.strip()
        if not (raw.startswith("[") and raw.endswith("]")):
            return None
        items = []
        for part in split_top_level(raw[1:-1]):
            part = part.strip()
            if not part:
                continue
            items.append(part[1:-1] if part.startswith('"') and part.endswith('"') else part)
        return items

    def as_object_keys(self) -> set[str] | None:
        raw = self.raw.strip()
        if not (raw.startswith("{") and raw.endswith("}")):
            return None
        return set(re.findall(r"^\s*([a-z_][a-z0-9_]*)\s*=", raw[1:-1], re.MULTILINE))


def split_top_level(text: str) -> list[str]:
    """括弧と文字列を跨がないカンマで分割する。"""
    parts, depth, in_str, esc, buf = [], 0, False, False, []
    for ch in text:
        if in_str:
            buf.append(ch)
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch in "[{(":
            depth += 1
        elif ch in "]})":
            depth -= 1
        elif ch == "," and depth == 0:
            parts.append("".join(buf))
            buf = []
            continue
        buf.append(ch)
    parts.append("".join(buf))
    return parts


def strip_comments(text: str) -> str:
    """行コメントを落とす。文字列の中の # は残す (パスワードに入りうる)。"""
    out = []
    for line in text.split("\n"):
        in_str, esc, cut = False, False, len(line)
        for i, ch in enumerate(line):
            if in_str:
                if esc:
                    esc = False
                elif ch == "\\":
                    esc = True
                elif ch == '"':
                    in_str = False
                continue
            if ch == '"':
                in_str = True
            elif ch == "#" or (ch == "/" and line[i + 1 : i + 2] == "/"):
                cut = i
                break
        out.append(line[:cut])
    return "\n".join(out)


def parse_tfvars(text: str, source: str) -> dict[str, Value]:
    """行頭の `name = ...` を拾う。値は次の代入の直前まで (複数行のリスト/オブジェクト対策)。

    BOM を落としているのは、Windows のエディタや PowerShell の Out-File が付けた BOM が
    先頭行の変数名にくっついて「未設定」に見えるため (terraform 自身は BOM を許容する)。
    """
    body = strip_comments(text.replace("﻿", "").replace("\r\n", "\n"))
    hits = list(re.finditer(r"^([a-z_][a-z0-9_]*)[ \t]*=[ \t]*", body, re.MULTILINE))
    out: dict[str, Value] = {}
    for i, m in enumerate(hits):
        end = hits[i + 1].start() if i + 1 < len(hits) else len(body)
        out[m.group(1)] = Value(m.group(1), body[m.end() : end].strip(), source)
    return out


def declared_variables() -> dict[str, dict]:
    """variables.tf の変数名 → {default: bool, sensitive: bool}。"""
    text = read("terraform/variables.tf")
    out: dict[str, dict] = {}
    for m in re.finditer(r'^variable\s+"([^"]+)"\s*\{', text, re.MULTILINE):
        depth, i = 1, m.end()
        while i < len(text) and depth > 0:
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
            i += 1
        block = text[m.end() : i - 1]
        out[m.group(1)] = {
            "default": re.search(r"^\s*default\s*=", block, re.MULTILINE) is not None,
            "sensitive": re.search(r"^\s*sensitive\s*=\s*true", block, re.MULTILINE) is not None,
        }
    return out


def spec_notes() -> dict[str, str]:
    """docs/spec/08-parameters.md の表から変数ごとの「入手元 / 備考」を拾う。

    入手元をここに書き写すと二重管理になる。仕様書が正。
    """
    notes: dict[str, str] = {}
    try:
        text = read("docs/spec/08-parameters.md")
    except OSError:
        return notes
    for line in text.splitlines():
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        m = re.fullmatch(r"`([a-z_][a-z0-9_]*)`", cells[0]) if cells else None
        if not m or len(cells) < 3:
            continue
        note = re.sub(r"[`*]", "", cells[-1]).strip()
        if note and note != "-":
            notes[m.group(1)] = note
    return notes


# ------------------------------------------------------------ 値の素性

# サンプルの値のままだと確実に動かないもの。
MUST_CHANGE = {
    "tenancy_ocid",
    "compartment_ocid",
    "ssh_public_key",
    "home_ip_cidr",
    "tailscale_authkey_server",
    "tailscale_authkey_monitor",
    "rcon_password",
    "discord_webhook_url",
    "r2_access_key_id",
    "r2_secret_access_key",
    "r2_endpoint",
}

PLACEHOLDER = re.compile(
    r"xxxx|yyyy|<account-id>|AAAA\.\.\.|203\.0\.113\.|generated-rcon-password"
    r"|friend1_mcid|friend2_mcid|admin_mcid|100\.x\.x\.",
    re.IGNORECASE,
)

# (正規表現, NG にするか, 説明)。形が違えば apply か実行時に必ず失敗するものを NG にする。
FORMATS: dict[str, tuple[str, bool, str]] = {
    "tenancy_ocid": (r"^ocid1\.tenancy\.", True, "ocid1.tenancy. で始まる"),
    "compartment_ocid": (
        r"^ocid1\.(compartment|tenancy)\.",
        True,
        "ocid1.compartment. で始まる (ルートなら tenancy_ocid と同値)",
    ),
    "region": (r"^[a-z]{2,3}-[a-z]+-\d$", True, "ap-tokyo-1 のような識別子"),
    "zerotier_network_id": (r"^[0-9a-f]{16}$", True, "16桁の16進数"),
    "ssh_public_key": (
        r"^(ssh-ed25519|ssh-rsa|ecdsa-sha2-\S+)\s+[A-Za-z0-9+/=]{30,}",
        True,
        "`cat ~/.ssh/oci_mc.pub` の中身をそのまま",
    ),
    "tailscale_authkey_server": (r"^tskey-", False, "tskey-auth- で始まる"),
    "tailscale_authkey_monitor": (r"^tskey-", False, "tskey-auth- で始まる"),
    "discord_webhook_url": (
        r"^https://(ptb\.|canary\.)?discord(app)?\.com/api/webhooks/\d+/\S+$",
        False,
        "https://discord.com/api/webhooks/<id>/<token>",
    ),
    "r2_endpoint": (
        r"^https://\S+\.r2\.cloudflarestorage\.com/?$",
        False,
        "https://<account-id>.r2.cloudflarestorage.com",
    ),
    "mc_memory": (r"^\d+[GgMm]$", False, "8G のような指定"),
    "mc_router_scale_down_after": (r"^\d+[smh]$", False, "30m のような指定"),
    "home_ip_cidr": (r"^\d+\.\d+\.\d+\.\d+/\d+$", True, "203.0.113.5/32 のような CIDR"),
}

# .env に書き出され docker compose が解釈する値。壊す文字を弾く。
ENV_BOUND = ("rcon_password", "playit_secret_key")
ENV_BREAKING = re.compile(r"[\s\"'$#\\`]")


def show(name: str, value: str, sensitive: bool) -> str:
    if sensitive:
        return f"設定済み ({len(value)}文字)"
    return value if len(value) <= 44 else value[:41] + "..."


# ------------------------------------------------------------ 検査

def check_tools() -> None:
    sec = "手元のツール"

    if shutil.which("terraform"):
        want = read("terraform/.terraform-version").strip()
        # tenv は作業ディレクトリの .terraform-version を読む。terraform/ で起動する。
        _, got = run(["terraform", "-version"], cwd=ROOT / "terraform")
        have = re.search(r"v?(\d+\.\d+\.\d+)", got)
        if have and have.group(1) == want:
            add("OK", sec, f"terraform {have.group(1)} (.terraform-version と一致)")
        elif have:
            add(
                "警告",
                sec,
                f"terraform {have.group(1)} だが .terraform-version は {want}。"
                f"tenv 経由で起動していない可能性がある (`tenv tf install`)",
            )
        else:
            add("警告", sec, "terraform のバージョンを取得できなかった")
    else:
        add("NG", sec, "terraform がない。tenv で導入する (docs/spec/A2-toolchain.md)")

    if not shutil.which("tenv"):
        add("警告", sec, "tenv がない。.terraform-version が効かず版がずれる")
    if not shutil.which("uv"):
        add("NG", sec, "uv がない。補助スクリプトと monitor の依存解決に要る")
    if not shutil.which("oci"):
        add("情報", sec, "oci CLI がない。apply には不要 (コンパートメント OCID の確認に使う)")

    if (ROOT / "terraform" / ".terraform" / "providers").is_dir():
        add("OK", sec, "terraform init 済み")
    else:
        add("警告", sec, "terraform/.terraform/ がない。`cd terraform && terraform init` が先")


def run(cmd: list[str], cwd: Path | None = None, timeout: int = 30) -> tuple[int, str]:
    """(終了コード, 標準出力+標準エラー)。起動できなければ (-1, "")。"""
    try:
        p = subprocess.run(
            cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout, encoding="utf-8",
            errors="replace",
        )
    except (OSError, subprocess.SubprocessError):
        return -1, ""
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def check_oci_auth(tfvars: dict[str, Value]) -> None:
    """provider "oci" は region しか指定していない = APIキー認証が前提。"""
    sec = "OCI 認証"

    env_keys = ("OCI_TENANCY_OCID", "OCI_USER_OCID", "OCI_FINGERPRINT", "OCI_PRIVATE_KEY_PATH")
    if all(os.environ.get(k) for k in env_keys):
        add("OK", sec, "OCI_* 環境変数で認証情報が揃っている")
        return

    override = os.environ.get("OCI_CONFIG_FILE", "").strip()
    path = Path(override).expanduser() if override else Path.home() / ".oci" / "config"
    if not path.is_file():
        add(
            "NG",
            sec,
            f"{path} がない。`oci setup config` で作り、公開鍵をコンソールに登録する "
            f"(docs/manual/01-prerequisites.md 手順1)",
        )
        return

    profile = os.environ.get("OCI_CONFIG_PROFILE", "DEFAULT")
    cp = configparser.ConfigParser()
    try:
        cp.read(path, encoding="utf-8")
    except configparser.Error as e:
        add("NG", sec, f"{path} を読めない: {e}")
        return
    if not cp.has_section(profile) and profile != "DEFAULT":
        add("NG", sec, f"{path} に [{profile}] プロファイルがない")
        return
    conf = dict(cp[profile]) if cp.has_section(profile) else dict(cp.defaults())

    missing = [k for k in ("user", "fingerprint", "key_file", "tenancy", "region") if not conf.get(k)]
    if missing:
        add("NG", sec, f"{path} の [{profile}] に {', '.join(missing)} がない")
    else:
        add("OK", sec, f"{path} [{profile}] に必要な項目が揃っている")

    key_file = conf.get("key_file", "")
    if key_file:
        kp = Path(os.path.expandvars(key_file)).expanduser()
        if not kp.is_file():
            add("NG", sec, f"key_file が指す {kp} がない (APIキーの秘密鍵)")

    tf_tenancy = get_str(tfvars, "tenancy_ocid")
    if tf_tenancy and conf.get("tenancy") and conf["tenancy"] != tf_tenancy:
        add(
            "警告",
            sec,
            "~/.oci/config の tenancy と tfvars の tenancy_ocid が違う。"
            "認証するテナンシーと作成先が食い違っていないか確認する",
        )
    tf_region = get_str(tfvars, "region")
    if tf_region and conf.get("region") and conf["region"] != tf_region:
        add("情報", sec, f"config の region ({conf['region']}) と var.region ({tf_region}) が違う")


def get_str(tfvars: dict[str, Value], name: str) -> str | None:
    v = tfvars.get(name)
    return v.as_string() if v else None


def check_files(has_tfvars: bool) -> None:
    sec = "入力ファイル"
    if has_tfvars:
        add("OK", sec, "terraform/terraform.tfvars がある")
    else:
        add(
            "NG",
            sec,
            "terraform/terraform.tfvars がない。"
            "`cp terraform/terraform.tfvars_sample terraform/terraform.tfvars` から始める",
        )

    # git ls-files は未追跡なら 1 を返す。出力にはパスが載るので終了コードで見る。
    code, _ = run(["git", "ls-files", "--error-unmatch", "terraform/terraform.tfvars"], cwd=ROOT)
    if code == 0:
        add("NG", sec, "terraform.tfvars が git の管理下に入っている。秘密がコミットされる")


def check_coverage(
    declared: dict[str, dict], merged: dict[str, Value], notes: dict[str, str]
) -> None:
    sec = "変数の充足"
    required = [n for n, d in declared.items() if not d["default"]]
    missing = [n for n in required if n not in merged]

    for name in missing:
        note = notes.get(name, "")
        add("NG", sec, f"必須変数 {name} が未設定" + (f" — 入手元: {trim(note, 70)}" if note else ""))
    if not missing:
        add("OK", sec, f"必須変数 {len(required)} 個はすべて設定されている")

    # 宣言にない名前。terraform は警告を出すだけで黙って無視するため、
    # 既定値のある変数の綴り違いは apply が通ってしまう (= 設定が効かない)。
    for name, v in sorted(merged.items()):
        if name in declared:
            continue
        near = difflib.get_close_matches(name, declared.keys(), n=1, cutoff=0.7)
        hint = f" ({near[0]} の綴り違いでは)" if near else ""
        add(
            "NG",
            sec,
            f"{v.source} の {name} は variables.tf に宣言がない{hint}。"
            f"terraform は警告だけ出して無視する",
        )

    unset_optional = [n for n, d in declared.items() if d["default"] and n not in merged]
    if unset_optional:
        add("情報", sec, f"既定値のまま: {', '.join(sorted(unset_optional))}")


def check_values(declared: dict[str, dict], merged: dict[str, Value], sample: dict[str, Value]) -> None:
    sec = "値の形"
    clean = True

    for name, v in sorted(merged.items()):
        if name not in declared:
            continue
        sensitive = declared[name]["sensitive"]
        s = v.as_string()
        if s is None:
            continue

        if not s.strip() and name in MUST_CHANGE:
            add("NG", sec, f"{name} が空")
            clean = False
            continue
        if not s.strip():
            continue

        smp = sample.get(name)
        if name in MUST_CHANGE and smp and smp.raw == v.raw:
            add("NG", sec, f"{name} がサンプルの値のまま")
            clean = False
            continue
        if PLACEHOLDER.search(s):
            add("NG", sec, f"{name} にプレースホルダが残っている ({show(name, s, sensitive)})")
            clean = False
            continue

        if s != s.strip() or "\r" in s or "\n" in s:
            add(
                "NG",
                sec,
                f"{name} の値に前後の空白か改行が混ざっている。"
                f".env 経由で VM に渡ると値末尾の \\r で RCON 認証が理由不明に失敗する",
            )
            clean = False

        if name in FORMATS:
            rx, fatal, desc = FORMATS[name]
            if not re.match(rx, s):
                add("NG" if fatal else "警告", sec, f"{name} の形が想定と違う。期待: {desc}")
                clean = False

        if name in ENV_BOUND and ENV_BREAKING.search(s):
            add(
                "NG",
                sec,
                f"{name} に空白か {chr(34)}'$#\\` が含まれる。"
                f".env に書き出され docker compose が解釈するため壊れる "
                f"(`openssl rand -base64 24` の出力なら安全)",
            )
            clean = False

    rcon = get_str(merged, "rcon_password")
    if rcon and len(rcon) < 16:
        add("警告", sec, f"rcon_password が {len(rcon)} 文字と短い。`openssl rand -base64 24` で生成する")
        clean = False

    for name in ("mc_whitelist", "mc_ops"):
        v = merged.get(name)
        items = v.as_list() if v else None
        for mcid in items or []:
            if not re.fullmatch(r"[A-Za-z0-9_]{3,16}", mcid):
                add("警告", sec, f"{name} の {mcid!r} は Minecraft ID の形式ではない (黙って無視される)")
                clean = False

    v = merged.get("mc_plugins")
    for pid in (v.as_list() if v else None) or []:
        if not re.fullmatch(r"\d+", pid):
            add("警告", sec, f"mc_plugins の {pid!r} は SpigotMC のリソースID (数字) ではない")
            clean = False

    v = merged.get("monitor_thresholds")
    keys = v.as_object_keys() if v else None
    if keys is not None and keys != {"cpu", "memory", "disk", "tps"}:
        add(
            "NG",
            sec,
            f"monitor_thresholds のキーが {sorted(keys)}。"
            f"cpu / memory / disk / tps をすべて書く (オブジェクト型なので部分指定できない)",
        )
        clean = False

    v = merged.get("ad_index")
    n = v.as_number() if v else None
    if n is not None and n not in (0, 1, 2):
        add("警告", sec, f"ad_index = {n:g}。東京リージョンの AD は 1 つ (0) で、Out of Capacity 時に 1,2 を試す")
        clean = False

    if clean:
        add("OK", sec, "設定済みの値に形式上の問題はない")


def check_semantics(merged: dict[str, Value], online: bool) -> None:
    """terraform が通してしまう組み合わせを見る。"""
    sec = "組み合わせ・運用上の前提"

    def b(name: str, fallback: bool) -> bool:
        v = merged.get(name)
        r = v.as_bool() if v else None
        return fallback if r is None else r

    mode = get_str(merged, "exposure_mode") or "playit"
    home_ssh = b("enable_home_ssh", True)
    home_cidr = get_str(merged, "home_ip_cidr") or ""

    # --- SSH の穴 (variables.tf の validation と同じだが、apply を待たずに出す)
    if home_ssh and not home_cidr:
        add("NG", sec, "enable_home_ssh = true なのに home_ip_cidr が空。`curl -s https://ifconfig.me`")
    elif home_ssh and home_cidr and not home_cidr.endswith("/32"):
        add("警告", sec, f"home_ip_cidr = {home_cidr} は /32 より広い。SSH を開ける範囲が広がる")
    if home_ssh and home_cidr and online:
        now = global_ip()
        if now and not home_cidr.startswith(now + "/"):
            add(
                "警告",
                sec,
                f"現在のグローバルIP ({now}) が home_ip_cidr ({home_cidr}) と違う。"
                f"このままだと初回の SSH フォールバックが自分に効かない",
            )
        elif now:
            add("OK", sec, f"home_ip_cidr が現在のグローバルIP ({now}) と一致")
    if not home_ssh:
        add(
            "情報",
            sec,
            "enable_home_ssh = false。Tailscale で両 VM に入れることを確認してから閉じる "
            "(docs/manual/02-post-setup.md 手順2)。未確認で閉じるとどこからも入れない",
        )

    # --- Tailscale の 2 本のキー
    ks, km = get_str(merged, "tailscale_authkey_server"), get_str(merged, "tailscale_authkey_monitor")
    if ks and km and ks == km:
        add(
            "NG",
            sec,
            "tailscale_authkey_server と _monitor が同じ値。"
            "tag:mc-server / tag:mc-monitor を付けた別々のキーを 2 本発行する "
            "(タグが違うと ACL の SSH ポリシーが効かない)",
        )

    # --- 公開方式
    if mode == "playit":
        if not (get_str(merged, "playit_secret_key") or "").strip():
            add(
                "警告",
                sec,
                "exposure_mode = playit だが playit_secret_key が空。"
                "このままだと playit コンテナが exit 1 で即終了する。"
                "先にセットアップウィザードで発行するか、apply 後に tfvars へ入れて "
                "`terraform apply && ansible-playbook site.yml -t app` で配送する",
            )
        if not (merged["mc_whitelist"].as_list() if "mc_whitelist" in merged else None):
            add(
                "警告",
                sec,
                "mc_whitelist が空でホワイトリストが無効。"
                "playit は誰でも到達できる公開アドレスなので、MCID を入れておく",
            )
    else:
        if (get_str(merged, "playit_secret_key") or "").strip():
            add("情報", sec, f"exposure_mode = {mode} では playit_secret_key は使われない")
        if any(k.startswith("mc_router_") for k in merged):
            add("情報", sec, f"exposure_mode = {mode} では mc_router_* は使われない (playit 専用)")

    if mode == "zerotier" or b("enable_zerotier", False):
        if not (get_str(merged, "zerotier_network_id") or "").strip():
            add("NG", sec, "ZeroTier を使う設定だが zerotier_network_id が空")

    if not (merged["mc_ops"].as_list() if "mc_ops" in merged else None):
        add("警告", sec, "mc_ops が空。ゲーム内から管理する手段がなくなる (RCON は残る)")

    if b("mc_router_auto_scale", False):
        add(
            "警告",
            sec,
            "mc_router_auto_scale = true。停止中は monitor.py が DOWN と誤報し backup.sh も実行できない "
            "(docs/spec/04-monitoring.md)",
        )

    # --- 監視
    fs = get_str(merged, "filesystem_name")
    if fs in (None, "/"):
        add(
            "情報",
            sec,
            "filesystem_name が既定の / のまま。構築後にメトリクス・エクスプローラで実測値を確認して直す "
            "(/dev/sda1 のことがある。docs/manual/02-post-setup.md 手順8)",
        )

    # --- バックアップ
    if b("enable_oci_backup", True):
        add("OK", sec, "OCI Object Storage への二次コピーが有効 (バケットは Terraform が作る)")
    else:
        add("情報", sec, "enable_oci_backup = false。バックアップ先が R2 だけになる")
    add("情報", sec, "R2 のバケットは Terraform が作らない。Cloudflare 側で作成済みか確認する")

    mem = get_str(merged, "mc_memory")
    if mem and re.fullmatch(r"\d+[Gg]", mem) and int(mem[:-1]) > 10:
        add("警告", sec, f"mc_memory = {mem}。VM は 12GB。OS とページキャッシュの余地がなくなる")


def global_ip() -> str | None:
    try:
        req = urllib.request.Request("https://ifconfig.me/ip", headers={"User-Agent": "curl/8"})
        with urllib.request.urlopen(req, timeout=10) as res:
            ip = res.read().decode("utf-8").strip()
        return ip if re.fullmatch(r"\d+\.\d+\.\d+\.\d+", ip) else None
    except (urllib.error.URLError, OSError, UnicodeDecodeError):
        return None


def check_ssh_key(merged: dict[str, Value]) -> None:
    sec = "SSH 鍵"
    pub = (get_str(merged, "ssh_public_key") or "").strip()
    if not pub:
        return
    body = pub.split()[1] if len(pub.split()) > 1 else ""
    sshdir = Path.home() / ".ssh"
    if not body:
        return
    for p in sorted(sshdir.glob("*.pub")) if sshdir.is_dir() else []:
        try:
            if body in p.read_text(encoding="utf-8", errors="replace"):
                priv = p.with_suffix("")
                if priv.is_file():
                    add("OK", sec, f"対応する秘密鍵がある ({priv})")
                else:
                    add("警告", sec, f"{p} はあるが秘密鍵 {priv} がない。初回の SSH ができない")
                return
        except OSError:
            continue
    add(
        "警告",
        sec,
        "ssh_public_key に対応する鍵が ~/.ssh/ に見つからない。"
        "初回構築のフォールバック SSH に使う秘密鍵の所在を確認する",
    )


def check_day2() -> None:
    sec = "Ansible (day-2)"
    inv = ROOT / "ansible" / "inventory.yml"
    if inv.is_file():
        add("OK", sec, "ansible/inventory.yml がある")
    else:
        add(
            "警告",
            sec,
            "ansible/inventory.yml がない。`cp ansible/inventory_sample.yml ansible/inventory.yml` "
            "(初回構築には不要。terraform apply だけでサーバーは動く)",
        )
    files = ROOT / "ansible" / "files"
    if (files / "docker-compose.yml").is_file() and (files / "mc-monitor.env").is_file():
        add("OK", sec, "ansible/files/ が生成されている")
    else:
        add("警告", sec, "ansible/files/ が未生成。先に `cd terraform && terraform apply`")

    if shutil.which("ansible-playbook"):
        add("OK", sec, "ansible-playbook がある")
    elif shutil.which("wsl"):
        _, out = run(["wsl", "-e", "which", "ansible-playbook"], timeout=40)
        if "ansible-playbook" in out:
            add("OK", sec, f"WSL 側に ansible-playbook がある ({out.strip().splitlines()[0]})")
        else:
            add("警告", sec, "WSL 側に ansible-playbook がない。Windows はコントロールノードにできない")
    else:
        add("警告", sec, "ansible も WSL もない。Ansible は WSL2 か mc-monitor 上から実行する")


# ------------------------------------------------------------ 出力

def width(s: str) -> int:
    return sum(2 if unicodedata.east_asian_width(c) in "WF" else 1 for c in s)


def trim(s: str, limit: int) -> str:
    out = []
    n = 0
    for ch in s:
        n += 2 if unicodedata.east_asian_width(ch) in "WF" else 1
        if n > limit:
            return "".join(out) + "…"
        out.append(ch)
    return "".join(out)


def wrap(msg: str, indent: int, limit: int = 100) -> list[str]:
    """全角混じりの折り返し。直前に空白があればそこで折る (識別子を割らない)。"""
    lines: list[str] = []
    buf: list[str] = []
    n = 0
    for ch in msg:
        w = 2 if unicodedata.east_asian_width(ch) in "WF" else 1
        if n + w > limit - indent:
            cut = next(
                (i for i in range(len(buf) - 1, max(len(buf) - 30, 0), -1) if buf[i] == " "),
                None,
            )
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


def report(day2: bool) -> int:
    counts = {"NG": 0, "警告": 0, "情報": 0, "OK": 0}
    for level, _, _ in results:
        counts[level] += 1

    for section in SECTIONS:
        if section == "Ansible (day-2)" and not day2:
            continue
        rows = [(lv, m) for lv, sec, m in results if sec == section]
        if not rows:
            continue
        print(f"\n== {section} ==")
        for level, msg in sorted(rows, key=lambda r: LEVEL_ORDER[r[0]]):
            head = f"  {level}" + " " * (5 - width(level))
            # 継続行のインデントは文字数ではなく表示幅で揃える (NG は2文字/幅2、警告は2文字/幅4)
            for i, line in enumerate(wrap(msg, width(head))):
                print(head + line if i == 0 else line)

    print(
        f"\nNG {counts['NG']} 件 / 警告 {counts['警告']} 件 / 情報 {counts['情報']} 件"
    )
    if counts["NG"]:
        print("NG を潰すまで terraform apply しない。値の入手元は docs/manual/01-prerequisites.md")
        return 1
    if counts["警告"]:
        print("警告は apply を止めないが、意図した設定か確認する")
    else:
        print("構築に必要な値は揃っている")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--online", action="store_true", help="グローバルIPを取得して home_ip_cidr と照合する")
    ap.add_argument("--day2", action="store_true", help="Ansible 側 (inventory.yml / ansible/files/) も見る")
    args = ap.parse_args()

    declared = declared_variables()
    notes = spec_notes()
    sample = parse_tfvars(read("terraform/terraform.tfvars_sample"), "terraform.tfvars_sample")

    # 優先度の低い順に重ねる: TF_VAR_ < terraform.tfvars < *.auto.tfvars
    merged: dict[str, Value] = {}
    for key, val in os.environ.items():
        if key.startswith("TF_VAR_"):
            merged[key[7:]] = Value(key[7:], f'"{val}"', "環境変数 " + key)

    tfvars_path = ROOT / "terraform" / "terraform.tfvars"
    if tfvars_path.is_file():
        merged.update(parse_tfvars(tfvars_path.read_text(encoding="utf-8"), "terraform.tfvars"))
    for p in sorted((ROOT / "terraform").glob("*.auto.tfvars")):
        merged.update(parse_tfvars(p.read_text(encoding="utf-8"), p.name))

    check_tools()
    check_files(tfvars_path.is_file())
    check_oci_auth(merged)
    check_coverage(declared, merged, notes)
    check_values(declared, merged, sample)
    check_semantics(merged, args.online)
    check_ssh_key(merged)
    if args.day2:
        check_day2()

    return report(args.day2)


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
