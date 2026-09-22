# テンプレートのレンダリング結果を手元に書き出して検査するための使い捨て構成。
#
# 本番の terraform/ とは独立しており、OCI プロバイダも認証情報も要らない
# (local プロバイダだけで動く)。exposure_mode の3値すべてを一度に出すので、
# 1つの方式だけ直して他を壊す事故を防げる。
#
#   cd scripts/render-check
#   terraform init
#   terraform apply -auto-approve -var proj=../..
#   python ../check-rendered.py out
#
# out/ は .gitignore 済み。

terraform {
  required_providers {
    local = {
      source  = "hashicorp/local"
      version = "~> 2.5"
    }
  }
}

variable "proj" {
  type        = string
  description = "リポジトリのルート (例: ../..)"
}

locals {
  modes = ["playit", "tailscale", "zerotier"]

  # ---------- docker-compose ----------

  # 3方式で共通のダミー値。方式ごとの分岐だけを差分として見たいので1箇所にまとめる。
  compose_common = {
    mc_private_ip          = "10.0.1.10"
    mc_memory              = "8G"
    mc_motd                = "OCI Minecraft Server"
    mc_difficulty          = "normal"
    mc_max_players         = 20
    mc_view_distance       = 8
    mc_simulation_distance = 6
    whitelist              = ["friend1", "friend2"]
    ops                    = ["admin1"]
    plugins                = ["8631", "28140"]

    mc_router_rate_limit       = 5
    mc_router_auto_scale       = false
    mc_router_scale_down_after = "30m"
  }

  compose = {
    for m in local.modes : m => templatefile(
      "${var.proj}/terraform/templates/docker-compose.yml.tftpl",
      merge(local.compose_common, { exposure_mode = m })
    )
  }

  # リストが空のときに ENFORCE_WHITELIST などの行が消えることを確認する
  compose_empty = templatefile(
    "${var.proj}/terraform/templates/docker-compose.yml.tftpl",
    merge(local.compose_common, {
      exposure_mode = "tailscale"
      whitelist     = []
      ops           = []
      plugins       = []
    })
  )

  # mc_router_auto_scale = true の分岐。既定 (false) とは mc-router の構成が
  # まるごと変わる (docker.sock / IN_DOCKER / mc 側のラベル) ため別に出す。
  compose_autoscale = templatefile(
    "${var.proj}/terraform/templates/docker-compose.yml.tftpl",
    merge(local.compose_common, {
      exposure_mode        = "playit"
      mc_router_auto_scale = true
    })
  )

  # ---------- 設定ファイル ----------

  mc_env = templatefile("${var.proj}/terraform/templates/mc-server.env.tftpl", {
    rcon_password     = "DUMMY-rcon-password"
    playit_secret_key = ""
  })

  monitor_env = templatefile("${var.proj}/terraform/templates/mc-monitor.env.tftpl", {
    discord_webhook_url = "https://discord.com/api/webhooks/DUMMY/DUMMY"
    rcon_host           = "10.0.1.10"
    rcon_password       = "DUMMY-rcon-password"
    arm_instance_ocid   = "ocid1.instance.oc1..DUMMY"
    compartment_ocid    = "ocid1.compartment.oc1..DUMMY"
    filesystem_name     = "/dev/sda1"
    threshold_cpu       = 85
    threshold_memory    = 85
    threshold_disk      = 80
    threshold_tps       = 15
  })

  rclone_conf = templatefile("${var.proj}/terraform/templates/rclone.conf.tftpl", {
    r2_access_key_id     = "DUMMY"
    r2_secret_access_key = "DUMMY"
    r2_endpoint          = "https://DUMMY.r2.cloudflarestorage.com"
  })

  # ---------- シェルスクリプト ----------

  backup_sh = templatefile("${var.proj}/terraform/templates/backup.sh.tftpl", {
    r2_bucket          = "minecraft-backup"
    remote_keep_days   = 30
    keep_generations   = 7
    enable_oci_backup  = true
    oci_namespace      = "dummyns"
    backup_bucket_name = "minecraft-backup"
  })

  # OCI バックアップ無効・世代整理なしの分岐も出す
  backup_sh_min = templatefile("${var.proj}/terraform/templates/backup.sh.tftpl", {
    r2_bucket          = "minecraft-backup"
    remote_keep_days   = 0
    keep_generations   = 0
    enable_oci_backup  = false
    oci_namespace      = "dummyns"
    backup_bucket_name = "minecraft-backup"
  })

  playit_check = templatefile("${var.proj}/terraform/templates/playit-check.sh.tftpl", {
    discord_webhook_url = "https://discord.com/api/webhooks/DUMMY/DUMMY"
  })

  # ---------- cloud-init ----------

  server_ci = {
    for m in local.modes : m => templatefile("${var.proj}/terraform/cloud-init/mc-server.yaml.tftpl", {
      exposure_mode       = m
      subnet_cidr         = "10.0.1.0/24"
      mc_private_ip       = "10.0.1.10"
      tailscale_authkey   = "tskey-auth-DUMMY"
      install_zerotier    = m == "zerotier"
      zerotier_network_id = "0123456789abcdef"
      enable_oci_backup   = true
      docker_compose      = local.compose[m]
      mc_env              = local.mc_env
      backup_sh           = local.backup_sh
      rclone_conf         = local.rclone_conf
      playit_check        = local.playit_check
    })
  }

  monitor_ci = templatefile("${var.proj}/terraform/cloud-init/mc-monitor.yaml.tftpl", {
    tailscale_authkey    = "tskey-auth-DUMMY"
    install_zerotier     = true
    zerotier_network_id  = "0123456789abcdef"
    enable_monitor_timer = true
    monitor_env          = local.monitor_env
    monitor_py           = file("${var.proj}/monitor/monitor.py")
    requirements_txt     = file("${var.proj}/monitor/requirements.txt")
    monitor_service      = file("${var.proj}/monitor/systemd/mc-monitor.service")
    monitor_timer        = file("${var.proj}/monitor/systemd/mc-monitor.timer")
  })
}

# ---------- 書き出し ----------
# 本番と同じ改行コード正規化をかける。ここで落とすと CRLF の混入を
# 検査できなくなるため、あえて raw のまま出す。

resource "local_file" "compose" {
  for_each        = local.compose
  filename        = "${path.module}/out/docker-compose.${each.key}.yml"
  content         = each.value
  file_permission = "0644"
}

resource "local_file" "compose_empty" {
  filename        = "${path.module}/out/docker-compose.empty-lists.yml"
  content         = local.compose_empty
  file_permission = "0644"
}

resource "local_file" "compose_autoscale" {
  filename        = "${path.module}/out/docker-compose.playit-autoscale.yml"
  content         = local.compose_autoscale
  file_permission = "0644"
}

resource "local_file" "server_ci" {
  for_each        = local.server_ci
  filename        = "${path.module}/out/mc-server.${each.key}.yaml"
  content         = each.value
  file_permission = "0644"
}

resource "local_file" "monitor_ci" {
  filename        = "${path.module}/out/mc-monitor.yaml"
  content         = local.monitor_ci
  file_permission = "0644"
}

resource "local_file" "backup_sh" {
  filename        = "${path.module}/out/backup.sh"
  content         = local.backup_sh
  file_permission = "0644"
}

resource "local_file" "backup_sh_min" {
  filename        = "${path.module}/out/backup.min.sh"
  content         = local.backup_sh_min
  file_permission = "0644"
}

resource "local_file" "playit_check" {
  filename        = "${path.module}/out/playit-check.sh"
  content         = local.playit_check
  file_permission = "0644"
}

resource "local_file" "mc_env" {
  filename        = "${path.module}/out/mc-server.env"
  content         = local.mc_env
  file_permission = "0644"
}

resource "local_file" "monitor_env" {
  filename        = "${path.module}/out/mc-monitor.env"
  content         = local.monitor_env
  file_permission = "0644"
}

resource "local_file" "rclone_conf" {
  filename        = "${path.module}/out/rclone.conf"
  content         = local.rclone_conf
  file_permission = "0644"
}

# docker compose config を通すための .env (compose の変数展開に必要)
resource "local_file" "compose_dotenv" {
  filename        = "${path.module}/out/.env"
  content         = "RCON_PASSWORD=DUMMY-rcon-password\nPLAYIT_SECRET_KEY=\n"
  file_permission = "0644"
}
