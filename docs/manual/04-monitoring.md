# 04. 監視・通知（monitor.py）

保存先: `docs/04-monitoring.md`

## 役割

```
1. 読む
   ├─ RCON → TPS、プレイヤー数、死活
   └─ OCI Monitoring API → CPU、メモリ、ディスク

2. 判定する
   └─ 閾値と比較し、状態変化を検出

3. 書く
   ├─ Discord Webhook → アラート通知
   └─ OCI Monitoring API → TPS/プレイヤー数を記録（Dashboards用）
```

CPU・メモリ・ディスクは Oracle Cloud Agent が自動収集するため、monitor.py を止めてもそちらは動き続けます。TPS・プレイヤー数・Discord通知だけが止まります。

## monitor.py

ローカルで作成します。`FILESYSTEM_NAME` は `03-post-setup.md` の手順8で確認した値に置き換えてください。

```python
import json
import os
import re
from datetime import datetime, timedelta, timezone

import oci
import requests
from dotenv import load_dotenv
from mcrcon import MCRcon

load_dotenv()

WEBHOOK = os.environ["DISCORD_WEBHOOK_URL"]
RCON_HOST = os.environ["RCON_HOST"]
RCON_PORT = int(os.environ["RCON_PORT"])
RCON_PASSWORD = os.environ["RCON_PASSWORD"]
INSTANCE_OCID = os.environ["ARM_INSTANCE_OCID"]
COMPARTMENT_OCID = os.environ["COMPARTMENT_OCID"]

STATE_FILE = "/home/ubuntu/monitor_state.json"
CUSTOM_NAMESPACE = "custom_minecraft"

# 03の手順8で確認した実際の値に置き換える
FILESYSTEM_NAME = "/"

THRESHOLDS = {
    "cpu": 85.0,
    "memory": 85.0,
    "disk": 80.0,
    "tps": 15.0,
}

signer = oci.auth.signers.InstancePrincipalsSecurityTokenSigner()
monitoring = oci.monitoring.MonitoringClient(config={}, signer=signer)


def query_metric(namespace, query):
    now = datetime.now(timezone.utc)
    details = oci.monitoring.models.SummarizeMetricsDataDetails(
        namespace=namespace,
        query=query,
        start_time=now - timedelta(minutes=10),
        end_time=now,
    )
    resp = monitoring.summarize_metrics_data(
        compartment_id=COMPARTMENT_OCID,
        summarize_metrics_data_details=details,
    )
    if not resp.data or not resp.data[0].aggregated_datapoints:
        return None
    return resp.data[0].aggregated_datapoints[-1].value


def get_infra_metrics():
    rid = f'{{resourceId = "{INSTANCE_OCID}"}}'
    return {
        "cpu": query_metric("oci_computeagent", f"CpuUtilization[5m]{rid}.mean()"),
        "memory": query_metric("oci_computeagent", f"MemoryUtilization[5m]{rid}.mean()"),
        "disk": query_metric(
            "oci_computeagent",
            f'FilesystemUtilization[5m]{{resourceId = "{INSTANCE_OCID}", '
            f'fileSystemName = "{FILESYSTEM_NAME}"}}.mean()',
        ),
    }


def get_mc_metrics():
    try:
        with MCRcon(RCON_HOST, RCON_PASSWORD, port=RCON_PORT) as mcr:
            tps_raw = re.sub(r"§.", "", mcr.command("tps"))
            nums = re.findall(r"\d+\.?\d*", tps_raw)
            tps = float(nums[-3]) if len(nums) >= 3 else None

            list_raw = re.sub(r"§.", "", mcr.command("list"))
            m = re.search(r"There are (\d+)", list_raw)
            players = int(m.group(1)) if m else None

        return {"online": True, "tps": tps, "players": players}
    except Exception as e:
        return {"online": False, "error": str(e)}


def post_custom_metrics(mc):
    """TPS・プレイヤー数・死活状態をOCI Monitoringへ送信"""
    now = datetime.now(timezone.utc)
    values = {}

    if mc["online"]:
        if mc.get("tps") is not None:
            values["TPS"] = mc["tps"]
        if mc.get("players") is not None:
            values["PlayerCount"] = float(mc["players"])
        values["ServerOnline"] = 1.0
    else:
        values["ServerOnline"] = 0.0

    metric_data = [
        oci.monitoring.models.MetricDataDetails(
            namespace=CUSTOM_NAMESPACE,
            compartment_id=COMPARTMENT_OCID,
            name=name,
            dimensions={"resourceId": INSTANCE_OCID, "resourceName": "mc-server"},
            datapoints=[oci.monitoring.models.Datapoint(timestamp=now, value=value)],
        )
        for name, value in values.items()
    ]

    if metric_data:
        details = oci.monitoring.models.PostMetricDataDetails(metric_data=metric_data)
        monitoring.post_metric_data(post_metric_data_details=details)


def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE) as f:
            return json.load(f)
    return {}


def save_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f)


def send_discord(title, lines, color):
    payload = {
        "embeds": [{
            "title": title,
            "description": "\n".join(lines),
            "color": color,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }]
    }
    requests.post(WEBHOOK, json=payload, timeout=10)


def main():
    prev = load_state()
    state = {}
    alerts = []
    recoveries = []

    infra = get_infra_metrics()
    mc = get_mc_metrics()

    checks = [
        ("cpu", infra["cpu"], THRESHOLDS["cpu"], "CPU使用率", "%", False),
        ("memory", infra["memory"], THRESHOLDS["memory"], "メモリ使用率", "%", False),
        ("disk", infra["disk"], THRESHOLDS["disk"], "ディスク使用率", "%", False),
    ]
    if mc["online"] and mc.get("tps") is not None:
        checks.append(("tps", mc["tps"], THRESHOLDS["tps"], "TPS", "", True))

    for key, value, threshold, label, unit, below in checks:
        if value is None:
            # メトリクスが取れなかった項目は前回の状態を保持する。
            # ここで state に書かないと、次回取得できた時に「初回超過」として
            # 再通知されてしまう。
            if key in prev:
                state[key] = prev[key]
            continue
        breached = value < threshold if below else value >= threshold
        state[key] = breached
        if breached and not prev.get(key):
            op = "下回りました" if below else "超えました"
            alerts.append(f"**{label}**: {value:.1f}{unit} (閾値 {threshold}{unit} を{op})")
        elif not breached and prev.get(key):
            recoveries.append(f"**{label}**: {value:.1f}{unit} に回復")

    state["offline"] = not mc["online"]
    if state["offline"] and not prev.get("offline"):
        alerts.append("**Minecraftサーバーが応答なし**(RCON接続失敗)")
    elif not state["offline"] and prev.get("offline"):
        recoveries.append(f"**Minecraftサーバー復旧**(プレイヤー {mc.get('players', 0)} 人)")

    # カスタムメトリクス送信。失敗してもDiscord通知は続行する
    try:
        post_custom_metrics(mc)
    except Exception as e:
        print(f"custom metric post failed: {e}")

    if alerts:
        send_discord("🚨 アラート", alerts, 0xE74C3C)
    if recoveries:
        send_discord("✅ 復旧", recoveries, 0x2ECC71)

    save_state(state)


if __name__ == "__main__":
    main()
```

閾値を超え続けている間は毎回通知せず、状態が変化した時だけ送ります。

## 配置

```bash
scp monitor.py ubuntu@mc-monitor:/home/ubuntu/
```

Tailscale 経由なので鍵指定は不要です。

## 強制発火テスト

```bash
ssh ubuntu@mc-monitor
# THRESHOLDS の "cpu" を一時的に 0.0 に書き換える
~/venv/bin/python3 ~/monitor.py
```

Discord に届いたら閾値を戻します。

## カスタムメトリクス送信の確認

コンソール → 監視 → メトリクス・エクスプローラ

| 項目 | 値 |
|---|---|
| ネームスペース | `custom_minecraft` |
| メトリック名 | `TPS`, `PlayerCount`, `ServerOnline` |

5分に1回しか送信していないため、データポイントが疎らに見えるのは正常です。

401 が出る場合は `iam.tf` の `use metrics` 権限が適用されているか確認してください。

## タイマー有効化

```bash
sudo systemctl enable --now mc-monitor.timer
systemctl list-timers mc-monitor.timer
journalctl -u mc-monitor.service -f
```

| コマンド | 用途 |
|---|---|
| `enable --now` | 自動起動設定 + 即時起動（初回のみ） |
| `list-timers` | 次回実行時刻の確認 |
| `journalctl -f` | 実行ログをリアルタイム表示 |

## 実行方式について

常駐プロセスではありません。systemd タイマーが5分おきに Python を起動し、1回の実行が終わるとプロセスは終了します。

```
mc-monitor.timer（5分ごと）
   ▼
mc-monitor.service（Type=oneshot）
   ▼
python3 monitor.py 実行 → 終了
```

1GB メモリの AMD Micro でも負担になりません。`systemctl status mc-monitor.service` が `inactive (dead)` なのは正常です。

## 実行間隔の変更

`/etc/systemd/system/mc-monitor.timer` の以下を編集します。

```ini
[Timer]
OnBootSec=5min          # 起動から初回実行までの待ち時間
OnUnitActiveSec=5min    # 前回実行から次回までの間隔
```

```bash
sudo systemctl daemon-reload
sudo systemctl restart mc-monitor.timer
```

`daemon-reload` をしないと古い設定のまま動き続けます。

## チェックリスト

```
[ ] FILESYSTEM_NAME を実測値に修正
[ ] monitor.py 配置
[ ] 強制発火テスト（Discord着弾確認）
[ ] カスタムメトリクス送信確認
[ ] タイマー有効化
```