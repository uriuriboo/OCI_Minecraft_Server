# PaperMC のゲームログ(join/leave等)を OCI Logging に送る。
# 収集対象は data/logs/latest.log (docker-compose.yml.tftpl の ./data:/data で
# 既にホスト上の実ファイルとして存在する)。cloud-init・docker-compose は変更しない。
#
# Unified Monitoring Agent 自体は compute.tf の agent_config で有効化する
# (Custom Logs Monitoring プラグイン)。ここで定義するのは「何を収集し、どこに送るか」。

resource "oci_logging_log_group" "minecraft" {
  count          = var.enable_game_log_collection ? 1 : 0
  compartment_id = var.compartment_ocid
  display_name   = "minecraft"
  description    = "Minecraft サーバーのログ"
}

resource "oci_logging_log" "minecraft_game" {
  count        = var.enable_game_log_collection ? 1 : 0
  display_name = "minecraft_game"
  log_group_id = oci_logging_log_group.minecraft[0].id
  log_type     = "CUSTOM"

  # 荒らし調査等で必要になったときに遡れれば十分なので30日で固定する。
  # 専用変数は作らない (docs/spec/05-backup.md の backup_remote_keep_days とは別軸)。
  retention_duration = 30
}

resource "oci_logging_unified_agent_configuration" "minecraft_game" {
  count          = var.enable_game_log_collection ? 1 : 0
  compartment_id = var.compartment_ocid
  display_name   = "minecraft-game-log"
  description    = "PaperMC の latest.log を OCI Logging へ tail 転送する"
  is_enabled     = true

  service_configuration {
    configuration_type = "LOGGING"

    sources {
      source_type = "LOG_TAIL"
      name        = "minecraft-game-log-source"
      paths       = ["/home/ubuntu/minecraft/data/logs/latest.log"]
    }

    destination {
      log_object_id = oci_logging_log.minecraft_game[0].id
    }
  }

  group_association {
    group_list = [oci_identity_dynamic_group.mc_server_logging[0].id]
  }
}
