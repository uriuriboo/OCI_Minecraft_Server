#!/usr/bin/env python3
"""mc-server の死活・性能を監視し、Discord へ通知して OCI Monitoring に記録する。

systemd タイマー (mc-monitor.timer) から 5 分ごとに oneshot で起動される。常駐しない
ため、前回の判定結果は STATE_FILE に持ち越して「状態が変化した時だけ」通知する。

設定は /home/ubuntu/.env から読み込む (env/mc-monitor.env_sample 参照)。
FILESYSTEM_NAME と閾値を環境変数にしているのは、実測値が構築後にしか確定せず、
ここを書き換えるために毎回 Python を編集したくないため。
"""

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
RCON_PORT = int(os.environ.get("RCON_PORT", "25575"))
RCON_PASSWORD = os.environ["RCON_PASSWORD"]
INSTANCE_OCID = os.environ["ARM_INSTANCE_OCID"]
COMPARTMENT_OCID = os.environ["COMPARTMENT_OCID"]

STATE_FILE = os.environ.get("STATE_FILE", "/home/ubuntu/monitor_state.json")
CUSTOM_NAMESPACE = os.environ.get("CUSTOM_NAMESPACE", "custom_minecraft")

# FilesystemUtilization の fileSystemName ディメンションの実測値。
# `/` ではなく `/dev/sda1` のようなデバイス名のことがある。
# コンソール → 監視 → メトリクス・エクスプローラで確認した値を入れる。
FILESYSTEM_NAME = os.environ.get("FILESYSTEM_NAME", "/")

THRESHOLDS = {
    "cpu": float(os.environ.get("THRESHOLD_CPU", "85.0")),
    "memory": float(os.environ.get("THRESHOLD_MEMORY", "85.0")),
    "disk": float(os.environ.get("THRESHOLD_DISK", "80.0")),
    "tps": float(os.environ.get("THRESHOLD_TPS", "15.0")),
}

_monitoring = None


def monitoring_client():
    """OCI Monitoring クライアントを遅延生成する。

    インスタンスプリンシパルが使えない環境 (ローカル実行など) でも import 時に
    落ちないようにするため。取得できない場合は None を返し、呼び出し側で
    メトリクス処理だけを飛ばして Discord 通知は継続させる。
    """
    global _monitoring
    if _monitoring is None:
        signer = oci.auth.signers.InstancePrincipalsSecurityTokenSigner()
        _monitoring = oci.monitoring.MonitoringClient(config={}, signer=signer)
    return _monitoring


def query_metric(namespace, query):
    now = datetime.now(timezone.utc)
    details = oci.monitoring.models.SummarizeMetricsDataDetails(
        namespace=namespace,
        query=query,
        start_time=now - timedelta(minutes=10),
        end_time=now,
    )
    resp = monitoring_client().summarize_metrics_data(
        compartment_id=COMPARTMENT_OCID,
        summarize_metrics_data_details=details,
    )
    if not resp.data or not resp.data[0].aggregated_datapoints:
        return None
    return resp.data[0].aggregated_datapoints[-1].value


def get_infra_metrics():
    """Oracle Cloud Agent が収集した CPU/メモリ/ディスクを取得する。

    API が使えない場合は全て None を返し、判定をスキップさせる。
    """
    rid = f'{{resourceId = "{INSTANCE_OCID}"}}'
    try:
        return {
            "cpu": query_metric("oci_computeagent", f"CpuUtilization[5m]{rid}.mean()"),
            "memory": query_metric("oci_computeagent", f"MemoryUtilization[5m]{rid}.mean()"),
            "disk": query_metric(
                "oci_computeagent",
                f'FilesystemUtilization[5m]{{resourceId = "{INSTANCE_OCID}", '
                f'fileSystemName = "{FILESYSTEM_NAME}"}}.mean()',
            ),
        }
    except Exception as e:
        print(f"infra metric query failed: {e}")
        return {"cpu": None, "memory": None, "disk": None}


def get_mc_metrics():
    try:
        with MCRcon(RCON_HOST, RCON_PASSWORD, port=RCON_PORT) as mcr:
            # Paper の /tps は "TPS from last 1m, 5m, 15m: 20.0, 20.0, 20.0" 形式。
            # 数値を全て拾うと [1, 5, 15, <1m>, <5m>, <15m>] になるため後ろから3番目が直近1分。
            # §x のカラーコードは先に除去する。
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
    """TPS・プレイヤー数・死活状態を OCI Monitoring へ送信する。"""
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
        monitoring_client().post_metric_data(post_metric_data_details=details)


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
