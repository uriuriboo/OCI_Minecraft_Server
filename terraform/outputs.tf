output "minecraft_public_ip" {
  description = "初回構築時のフォールバック用。enable_home_ssh=false 後は到達できない"
  value       = oci_core_instance.mc_server.public_ip
}

output "monitor_public_ip" {
  value = oci_core_instance.mc_monitor.public_ip
}

output "minecraft_instance_ocid" {
  description = "Dashboards の MQL や monitor.py の ARM_INSTANCE_OCID で使う"
  value       = oci_core_instance.mc_server.id
}

output "monitor_instance_ocid" {
  value = oci_core_instance.mc_monitor.id
}

output "ssh_bootstrap_minecraft" {
  value = "ssh -i ~/.ssh/oci_mc ubuntu@${oci_core_instance.mc_server.public_ip}"
}

output "ssh_bootstrap_monitor" {
  value = "ssh -i ~/.ssh/oci_mc ubuntu@${oci_core_instance.mc_monitor.public_ip}"
}

output "backup_bucket" {
  description = "OCI Object Storage の二次コピー先。enable_oci_backup=false なら null"
  value       = var.enable_oci_backup ? "${data.oci_objectstorage_namespace.current.namespace}/${oci_objectstorage_bucket.backup[0].name}" : null
}

output "exposure_mode" {
  value = var.exposure_mode
}

output "minecraft_connect_address" {
  description = "プレイヤーに渡す接続先"
  value = (
    var.exposure_mode == "playit"
    ? "playit.gg のダッシュボードで払い出された xxx.playit.gg のアドレス"
    : "mc-server:25565 (MagicDNS 無効なら `tailscale ip -4` の 100.x.x.x)"
  )
}

# dashboards/minecraft-dashboard.json の OCID プレースホルダをこの値で置換する。
# 置換手順は docs/manual/04-dashboard.md と docs/spec/04-monitoring.md にある。
output "dashboard_mql" {
  description = "OCI Dashboards のウィジェットに貼る MQL"
  value = {
    cpu    = "CpuUtilization[5m]{resourceId = \"${oci_core_instance.mc_server.id}\"}.mean()"
    memory = "MemoryUtilization[5m]{resourceId = \"${oci_core_instance.mc_server.id}\"}.mean()"
    disk   = "FilesystemUtilization[5m]{resourceId = \"${oci_core_instance.mc_server.id}\", fileSystemName = \"${var.filesystem_name}\"}.mean()"
    tps    = "TPS[5m]{resourceName = \"mc-server\"}.mean()"
    online = "ServerOnline[5m]{resourceName = \"mc-server\"}.min()"
    player = "PlayerCount[5m]{resourceName = \"mc-server\"}.max()"
  }
}
