# 動的グループとポリシーはテナンシールートにしか作成できない。
# そのため compartment_ocid ではなく tenancy_ocid を使う。
#
# テナンシールートへの作成権限がない場合は、このファイルを一旦外し、
# 同じ内容をコンソールで手動作成してください
# (コンソール → アイデンティティ → ドメイン → 動的グループ / ポリシー)。

# ---------- 監視VM: メトリクスの読み取りと投稿 ----------

resource "oci_identity_dynamic_group" "monitor" {
  compartment_id = var.tenancy_ocid
  name           = "dg-monitor-instances"
  description    = "Monitor VM for reading and posting metrics"
  matching_rule  = "ALL {instance.id = '${oci_core_instance.mc_monitor.id}'}"
}

resource "oci_identity_policy" "monitor_metrics" {
  compartment_id = var.tenancy_ocid
  name           = "policy-monitor-metrics"
  description    = "Allow monitor VM to read and post metrics"

  # カスタムメトリクス (TPS / PlayerCount / ServerOnline) の投稿には
  # `use metrics` が必要。`read metrics` だけだと post_metric_data が 401 になる。
  statements = [
    "Allow dynamic-group ${oci_identity_dynamic_group.monitor.name} to read metrics in compartment id ${var.compartment_ocid}",
    "Allow dynamic-group ${oci_identity_dynamic_group.monitor.name} to use metrics in compartment id ${var.compartment_ocid}",
  ]
}

# ---------- Minecraftサーバー: バックアップ先バケットへの書き込み ----------
# インスタンスプリンシパルで認証させ、VM 上に OCI の APIキーを置かない。
# 権限はバックアップ用バケット1つに限定する。

resource "oci_identity_dynamic_group" "mc_server" {
  count          = var.enable_oci_backup ? 1 : 0
  compartment_id = var.tenancy_ocid
  name           = "dg-mc-server-instances"
  description    = "Minecraft server VM for uploading backups"
  matching_rule  = "ALL {instance.id = '${oci_core_instance.mc_server.id}'}"
}

resource "oci_identity_policy" "mc_server_backup" {
  count          = var.enable_oci_backup ? 1 : 0
  compartment_id = var.tenancy_ocid
  name           = "policy-mc-server-backup"
  description    = "Allow Minecraft server VM to write backups to its bucket only"

  statements = [
    # バケット自体の読み取り (存在確認とアップロード先の解決に必要)
    "Allow dynamic-group ${oci_identity_dynamic_group.mc_server[0].name} to read buckets in compartment id ${var.compartment_ocid} where target.bucket.name = '${var.backup_bucket_name}'",
    # オブジェクトの作成・上書き・削除。where 句でバケットを限定している
    "Allow dynamic-group ${oci_identity_dynamic_group.mc_server[0].name} to manage objects in compartment id ${var.compartment_ocid} where target.bucket.name = '${var.backup_bucket_name}'",
  ]
}
