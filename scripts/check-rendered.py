#!/usr/bin/env python3
"""scripts/render-check が書き出したレンダリング結果を検査する。

本番の terraform/ を apply せずに、テンプレートの出力が壊れていないかを見る。
過去に実際に踏んだ2つのバグ (Terraform のエスケープ漏れ、CRLF の混入) を
回帰試験として持っている。

    cd scripts/render-check
    terraform init
    terraform apply -auto-approve -var proj=../..
    cd ../..
    uv run scripts/check-rendered.py scripts/render-check/out

PyYAML があれば cloud-init を構造まで検査する。無い場合は行ベースの検査に落ちる。
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

try:
    import yaml
except ImportError:  # PyYAML が無い環境でも動かす
    yaml = None

failures: list[str] = []
notes: list[str] = []


def fail(msg: str) -> None:
    failures.append(msg)


# ------------------------------------------------- 1. Terraform のエスケープ漏れ

# templatefile がエスケープとして扱うのは $${ と %%{ だけ。
# `$$((expr))` と書くと $$ が残り、bash では $$ が PID に展開されて壊れる。
BAD_PATTERNS = [
    (r"\$\$\(", "$$( が残っている (bash では $$ が PID に展開される)。テンプレート側を $( に直す"),
    (r"\$\$\{", "$${ が残っている (二重エスケープ)。テンプレート側を確認する"),
    (r"%\{\s*(if|for|else|endif|endfor)", "Terraform のテンプレートディレクティブが未評価で残っている"),
]


def check_escapes(files: list[Path]) -> None:
    for path in files:
        text = path.read_text(encoding="utf-8")
        for pattern, msg in BAD_PATTERNS:
            for m in re.finditer(pattern, text):
                line = text[: m.start()].count("\n") + 1
                fail(f"{path.name}:{line} {msg}")


# ------------------------------------------------------------- 2. 改行コード


def check_line_endings(files: list[Path]) -> None:
    """CRLF の混入を見る。

    cloud-init の write_files はテンプレートの中身をそのまま VM に埋め込むため、
    ここに CRLF があると VM 上で backup.sh の行継続が壊れ、.env の値末尾に \\r が
    付いて RCON 認証が理由の分からない失敗をする。
    """
    for path in files:
        if b"\r\n" in path.read_bytes():
            fail(f"{path.name} に CRLF が含まれている (.gitattributes の eol=lf を確認)")


# ------------------------------------------------------- 3. cloud-init の構造


# write_files に必ず含まれていてほしいパス
REQUIRED_FILES = {
    "mc-server": [
        "/etc/ssh/sshd_config.d/99-disable-password.conf",
        "/home/ubuntu/minecraft/docker-compose.yml",
        "/home/ubuntu/minecraft/.env",
        "/home/ubuntu/minecraft/backup.sh",
        "/home/ubuntu/.config/rclone/rclone.conf",
    ],
    "mc-monitor": [
        "/etc/ssh/sshd_config.d/99-disable-password.conf",
        "/home/ubuntu/.env",
        "/home/ubuntu/monitor.py",
        "/home/ubuntu/requirements.txt",
        "/etc/systemd/system/mc-monitor.service",
        "/etc/systemd/system/mc-monitor.timer",
    ],
}


def check_cloud_init(out: Path) -> None:
    for path in sorted(out.glob("mc-*.yaml")):
        kind = "mc-monitor" if path.name.startswith("mc-monitor") else "mc-server"

        if yaml is None:
            notes.append(f"{path.name}: PyYAML が無いため構造検査をスキップ")
            continue

        try:
            doc = yaml.safe_load(path.read_text(encoding="utf-8"))
        except Exception as e:
            fail(f"{path.name} が YAML として壊れている: {e}")
            continue

        wf = {w["path"]: w for w in doc.get("write_files", [])}
        for required in REQUIRED_FILES[kind]:
            if required not in wf:
                fail(f"{path.name}: write_files に {required} がない")

        # permissions は文字列でないと 0600 が10進数として解釈される
        for p, w in wf.items():
            perms = w.get("permissions")
            if perms is not None and not isinstance(perms, str):
                fail(f"{path.name}: {p} の permissions がクォートされていない ({perms!r})")
            if not str(w.get("content", "")).strip():
                fail(f"{path.name}: {p} の content が空")

        runcmd = doc.get("runcmd", [])
        if not runcmd:
            fail(f"{path.name}: runcmd が空")

        # monitor.py が途中で切れていないか (indent 指定を間違えると起きる)
        if kind == "mc-monitor":
            body = wf.get("/home/ubuntu/monitor.py", {}).get("content", "")
            if "if __name__" not in body:
                fail(f"{path.name}: monitor.py が途中で切れている (indent の指定を確認)")

        notes.append(
            f"{path.name}: write_files={len(wf)} runcmd={len(runcmd)} "
            f"packages={len(doc.get('packages', []))}"
        )


# --------------------------------------------- 4. exposure_mode ごとの整合性


def check_exposure_consistency(out: Path) -> None:
    """cloud-init の iptables と docker-compose の公開設定が矛盾しないか。

    exposure_mode を1つだけ直して他を壊す事故を検出する。
    """
    for mode in ("playit", "tailscale", "zerotier"):
        ci_path = out / f"mc-server.{mode}.yaml"
        dc_path = out / f"docker-compose.{mode}.yml"
        if not ci_path.exists() or not dc_path.exists():
            fail(f"{mode}: レンダリング結果が揃っていない")
            continue

        ci = ci_path.read_text(encoding="utf-8")
        dc = dc_path.read_text(encoding="utf-8")

        has_host_net = "network_mode: \"host\"" in dc
        has_25565_rule = "--dport 25565" in ci
        has_playit_svc = "playit-cloud/playit-agent" in dc

        if mode == "playit":
            if has_host_net:
                fail("playit: docker-compose が network_mode: host になっている (bridge であるべき)")
            if not has_playit_svc:
                fail("playit: docker-compose に playit-agent サービスがない")
            if has_25565_rule:
                fail("playit: 25565 をホストに出していないのに iptables ルールがある")
            if f"25575:25575" not in dc:
                fail("playit: RCON をプライベートIPにバインドする ports 指定がない")
        else:
            if not has_host_net:
                fail(f"{mode}: docker-compose が network_mode: host になっていない")
            if has_playit_svc:
                fail(f"{mode}: docker-compose に playit-agent が残っている")
            if not has_25565_rule:
                fail(f"{mode}: 25565 の iptables ルールがない")

            iface = "tailscale0" if mode == "tailscale" else "zt+"
            accept = ci.find(f"-i {iface} -p tcp --dport 25565 -j ACCEPT")
            drop = ci.find("-A INPUT -p tcp --dport 25565 -j DROP")
            if accept < 0:
                fail(f"{mode}: -i {iface} の ACCEPT ルールがない")
            elif drop < 0:
                fail(f"{mode}: 25565 の DROP ルールがない")
            elif accept > drop:
                # ACCEPT が DROP より後ろにあると全拒否になる
                fail(f"{mode}: ACCEPT が DROP より後ろにある (全拒否になる)")

        has_router = "itzg/mc-router" in dc
        if mode == "playit" and not has_router:
            fail("playit: docker-compose に mc-router サービスがない")
        if mode != "playit" and has_router:
            fail(f"{mode}: mc-router は playit 専用なのに残っている")

        notes.append(
            f"{mode}: host_net={has_host_net} playit={has_playit_svc} "
            f"25565_rule={has_25565_rule} mc_router={has_router}"
        )


# ------------------------------------------------------------- 5. mc-router


def _yaml_effective(path: Path) -> str:
    """コメント行を落とした本文。

    コメントに書いた語で検査が通ったり落ちたりしないようにする
    (check_empty_lists が踏んでいるのと同じ罠)。
    """
    lines = [ln for ln in path.read_text(encoding="utf-8").splitlines() if not ln.lstrip().startswith("#")]
    return "\n".join(lines)


def check_mc_router(out: Path) -> None:
    """mc_router_auto_scale の2形態が入れ替わっていないか。

    auto_scale=false では docker.sock を渡さずに DEFAULT だけで経路を決める。
    ここが崩れると、既定の構成が黙ってホスト root 相当の権限を持つことになる。
    """
    off = out / "docker-compose.playit.yml"
    on = out / "docker-compose.playit-autoscale.yml"
    if not off.exists() or not on.exists():
        fail("mc-router: playit / playit-autoscale のレンダリング結果が揃っていない")
        return

    off_text = _yaml_effective(off)
    on_text = _yaml_effective(on)

    # 既定 (auto_scale=false)
    if 'DEFAULT: "mc:25565"' not in off_text:
        fail("mc-router(既定): DEFAULT の経路指定がない (誰も mc に届かない)")
    if "docker.sock" in off_text:
        fail("mc-router(既定): auto_scale=false なのに docker.sock を渡している")
    if "IN_DOCKER" in off_text or "AUTO_SCALE" in off_text:
        fail("mc-router(既定): auto_scale=false なのに Docker 連携の設定が出ている")
    if "mc-router.default" in off_text:
        fail("mc-router(既定): Docker 検出を使わないのに mc-router.* ラベルが出ている")

    # auto_scale=true
    for token in (
        "/var/run/docker.sock",
        'IN_DOCKER: "true"',
        'AUTO_SCALE_UP: "true"',
        'AUTO_SCALE_DOWN: "true"',
        'user: "0:0"',
        "mc-router.default",
    ):
        if token not in on_text:
            fail(f"mc-router(auto_scale): {token} がない")
    if 'DEFAULT: "mc:25565"' in on_text:
        fail("mc-router(auto_scale): Docker 検出とDEFAULTが二重に指定されている")

    # 初回起動で mc-router が上がらないと、playit を繋いでも経路がない
    ci = out / "mc-server.playit.yaml"
    if ci.exists() and "up -d mc mc-router" not in ci.read_text(encoding="utf-8"):
        fail("mc-router: cloud-init の初回起動が mc-router を含んでいない")

    notes.append("mc-router: 既定は docker.sock なし / auto_scale 分岐あり")


# ----------------------------------------------------------- 6. 空リスト分岐


def check_empty_lists(out: Path) -> None:
    path = out / "docker-compose.empty-lists.yml"
    if not path.exists():
        return
    text = path.read_text(encoding="utf-8")
    for key in ("ENFORCE_WHITELIST", "WHITELIST", "OPS", "SPIGET_RESOURCES"):
        if key in text:
            fail(f"mc_whitelist/ops/plugins が空なのに {key} が出力されている")
    notes.append("空リスト分岐: ホワイトリスト等の行が出ていない")


# ------------------------------------------------------------------- 実行


def main() -> int:
    out = Path(sys.argv[1] if len(sys.argv) > 1 else "scripts/render-check/out")
    if not out.is_dir():
        print(f"{out} がありません。先に render-check を apply してください:")
        print("  cd scripts/render-check && terraform init && terraform apply -auto-approve -var proj=../..")
        return 1

    files = [p for p in sorted(out.iterdir()) if p.is_file() and p.name != ".env"]
    if not files:
        print(f"{out} が空です。")
        return 1

    check_escapes(files)
    check_line_endings(files)
    check_cloud_init(out)
    check_exposure_consistency(out)
    check_mc_router(out)
    check_empty_lists(out)

    for n in notes:
        print(f"  {n}")

    if failures:
        print(f"\nNG: {len(failures)} 件")
        for f in failures:
            print(f"  - {f}")
        return 1

    print(f"\nOK: {len(files)} ファイルを検査、問題なし")
    print("  ※ シェルスクリプトの構文は別途 `bash -n` を通すこと (WSL2):")
    print(f"     wsl -e bash -c 'cd $(wslpath -a {out}) && bash -n backup.sh backup.min.sh playit-check.sh'")
    return 0


if __name__ == "__main__":
    sys.exit(main())
