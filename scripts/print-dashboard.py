#!/usr/bin/env python3
"""dashboards/oci-dashboard.json の MQL に実 OCID を埋めて出力する。

コンソールでダッシュボードを作る際、ウィジェットのメトリック・クエリ欄に
貼り付けるための文字列を作る。OCID を毎回 terraform output から拾って
手で書き換える手間を省くためのもの。

    python scripts/print-dashboard.py            # terraform output から取得
    python scripts/print-dashboard.py --no-tf    # プレースホルダのまま出力

terraform output を使うには terraform/ で apply 済みである必要がある。
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEF_FILE = ROOT / "dashboards" / "oci-dashboard.json"


def terraform_outputs() -> dict:
    try:
        raw = subprocess.run(
            ["terraform", "-chdir=" + str(ROOT / "terraform"), "output", "-json"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout
    except FileNotFoundError:
        print("terraform コマンドが見つかりません。--no-tf で実行してください。", file=sys.stderr)
        return {}
    except subprocess.CalledProcessError as e:
        print(f"terraform output が失敗しました: {e.stderr.strip()}", file=sys.stderr)
        return {}
    return {k: v.get("value") for k, v in json.loads(raw).items()}


def main() -> int:
    use_tf = "--no-tf" not in sys.argv
    definition = json.loads(DEF_FILE.read_text(encoding="utf-8"))

    subs = {
        "__MC_SERVER_OCID__": "<minecraft_instance_ocid>",
        "__MC_MONITOR_OCID__": "<monitor_instance_ocid>",
        "__FILESYSTEM_NAME__": "/",
    }

    if use_tf:
        out = terraform_outputs()
        if out.get("minecraft_instance_ocid"):
            subs["__MC_SERVER_OCID__"] = out["minecraft_instance_ocid"]
        if out.get("monitor_instance_ocid"):
            subs["__MC_MONITOR_OCID__"] = out["monitor_instance_ocid"]
        # filesystem_name は output していないので dashboard_mql の disk から拾う
        mql = out.get("dashboard_mql") or {}
        disk = mql.get("disk", "")
        if 'fileSystemName = "' in disk:
            subs["__FILESYSTEM_NAME__"] = disk.split('fileSystemName = "')[1].split('"')[0]
        if not out:
            print("(terraform output が取れなかったため、プレースホルダで出力します)\n")

    def fill(text: str) -> str:
        for k, v in subs.items():
            text = text.replace(k, v)
        return text

    print(f"# {definition['title']}")
    print(f"#   既定の期間: {definition['defaultTimeRange']}  更新間隔: {definition['refreshInterval']}")
    print(f"#   {definition['_refreshNote']}")
    print()
    print("コンソール → 監視 → ダッシュボード → ダッシュボードの作成")
    print("各ウィジェットに以下を入力します。")
    print()

    current_row = None
    for w in definition["widgets"]:
        if w["row"] != current_row:
            current_row = w["row"]
            print(f"--- {current_row} 段目 ---")
        print(f"  [{w['title']}]  ({w['type']})")
        print(f"    ネームスペース : {w['namespace']}")
        print(f"    メトリック     : {w['metric']}")
        print(f"    MQL            : {fill(w['mql'])}")
        if w.get("mqlSecondary"):
            print(f"    MQL (2本目)    : {fill(w['mqlSecondary'])}")
        if w.get("valueMapping"):
            m = ", ".join(f"{k}={v}" for k, v in w["valueMapping"].items())
            print(f"    値のマッピング : {m}")
        if w.get("thresholds"):
            t = ", ".join(f"{k}={v}" for k, v in w["thresholds"].items())
            print(f"    しきい値       : {t}")
        if w.get("range"):
            print(f"    表示範囲       : {w['range']['min']} - {w['range']['max']}")
        if w.get("note"):
            print(f"    メモ           : {w['note']}")
        print()

    print("--- ダッシュボードに出せないもの ---")
    for n in definition["notDisplayable"]:
        print(f"  - {n}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
