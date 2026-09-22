# テンプレートの単一の正はここ。
#
# 同じ docker-compose.yml を cloud-init 用 (templatefile) と Ansible 用 (Jinja2) に
# 二重管理しないため、レンダリングは Terraform 側で一度だけ行い、
#   - cloud-init … 初回構築時にVM内へ埋め込む
#   - local_file … ansible/files/ へ書き出し、稼働後の更新に使う
# の2経路で同じ文字列を配る。

locals {
  # exposure_mode=zerotier なら当然 ZeroTier が必要。
  # enable_zerotier は「Tailscale と併設したい」場合に独立して立てるフラグ。
  install_zerotier = var.enable_zerotier || var.exposure_mode == "zerotier"

  raw_docker_compose = templatefile("${path.module}/templates/docker-compose.yml.tftpl", {
    exposure_mode          = var.exposure_mode
    mc_private_ip          = var.mc_private_ip
    mc_memory              = var.mc_memory
    mc_motd                = var.mc_motd
    mc_difficulty          = var.mc_difficulty
    mc_max_players         = var.mc_max_players
    mc_view_distance       = var.mc_view_distance
    mc_simulation_distance = var.mc_simulation_distance
    whitelist              = var.mc_whitelist
    ops                    = var.mc_ops
    plugins                = var.mc_plugins

    mc_router_rate_limit       = var.mc_router_rate_limit
    mc_router_auto_scale       = var.mc_router_auto_scale
    mc_router_scale_down_after = var.mc_router_scale_down_after
  })

  raw_mc_env = templatefile("${path.module}/templates/mc-server.env.tftpl", {
    rcon_password     = var.rcon_password
    playit_secret_key = var.playit_secret_key
  })

  raw_rclone_conf = templatefile("${path.module}/templates/rclone.conf.tftpl", {
    r2_access_key_id     = var.r2_access_key_id
    r2_secret_access_key = var.r2_secret_access_key
    r2_endpoint          = var.r2_endpoint
  })

  raw_backup_sh = templatefile("${path.module}/templates/backup.sh.tftpl", {
    r2_bucket          = var.r2_bucket
    remote_keep_days   = var.backup_remote_keep_days
    keep_generations   = var.backup_keep_generations
    enable_oci_backup  = var.enable_oci_backup
    oci_namespace      = data.oci_objectstorage_namespace.current.namespace
    backup_bucket_name = var.backup_bucket_name
  })

  raw_playit_check = templatefile("${path.module}/templates/playit-check.sh.tftpl", {
    discord_webhook_url = var.discord_webhook_url
  })

  # mc_server の OCID が必要なため、mc_server 作成後に確定する。
  raw_monitor_env = templatefile("${path.module}/templates/mc-monitor.env.tftpl", {
    discord_webhook_url = var.discord_webhook_url
    rcon_host           = var.mc_private_ip
    rcon_password       = var.rcon_password
    arm_instance_ocid   = oci_core_instance.mc_server.id
    compartment_ocid    = var.compartment_ocid
    filesystem_name     = var.filesystem_name
    threshold_cpu       = var.monitor_thresholds.cpu
    threshold_memory    = var.monitor_thresholds.memory
    threshold_disk      = var.monitor_thresholds.disk
    threshold_tps       = var.monitor_thresholds.tps
  })

  # monitor.py と systemd unit は monitor/ 配下が唯一の正。
  # テンプレートではないのでそのまま読み込む。
  raw_monitor_py       = file("${path.module}/../monitor/monitor.py")
  raw_requirements_txt = file("${path.module}/../monitor/requirements.txt")
  raw_monitor_service  = file("${path.module}/../monitor/systemd/mc-monitor.service")
  raw_monitor_timer    = file("${path.module}/../monitor/systemd/mc-monitor.timer")
}

locals {
  # ---------- 改行コードの正規化 ----------
  # ここで配る文字列はすべて Linux VM 上で実行・解釈される。
  # core.autocrlf=true の Windows でクローンするとテンプレートが CRLF になり、
  # cloud-init の write_files 経由でそのまま VM に埋め込まれて壊れる。
  #
  #   backup.sh     行継続の `\` が `\r` をエスケープして構文エラー
  #   .env          値の末尾に \r が付き RCON 認証が謎の失敗をする
  #   *.service     systemd が ExecStart の値を誤読する
  #
  # .gitattributes で eol=lf を指定しているが、それが効かない環境
  # (古いクローン、zip ダウンロード、エディタの設定) でも壊れないよう
  # ここでも落とす。
  docker_compose   = replace(local.raw_docker_compose, "\r\n", "\n")
  mc_env           = replace(local.raw_mc_env, "\r\n", "\n")
  rclone_conf      = replace(local.raw_rclone_conf, "\r\n", "\n")
  backup_sh        = replace(local.raw_backup_sh, "\r\n", "\n")
  playit_check     = replace(local.raw_playit_check, "\r\n", "\n")
  monitor_env      = replace(local.raw_monitor_env, "\r\n", "\n")
  monitor_py       = replace(local.raw_monitor_py, "\r\n", "\n")
  requirements_txt = replace(local.raw_requirements_txt, "\r\n", "\n")
  monitor_service  = replace(local.raw_monitor_service, "\r\n", "\n")
  monitor_timer    = replace(local.raw_monitor_timer, "\r\n", "\n")
}

# ---------- Ansible への受け渡し ----------
# ansible/files/ は .gitignore 済み。Ansible は Jinja2 テンプレートを持たず、
# ここに出力されたファイルを copy するだけの配送役になる。

resource "local_file" "ansible_docker_compose" {
  filename        = "${path.module}/../ansible/files/docker-compose.yml"
  content         = local.docker_compose
  file_permission = "0644"
}

resource "local_sensitive_file" "ansible_mc_env" {
  filename        = "${path.module}/../ansible/files/mc-server.env"
  content         = local.mc_env
  file_permission = "0600"
}

resource "local_sensitive_file" "ansible_monitor_env" {
  filename        = "${path.module}/../ansible/files/mc-monitor.env"
  content         = local.monitor_env
  file_permission = "0600"
}
