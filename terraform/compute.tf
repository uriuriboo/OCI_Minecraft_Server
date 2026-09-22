data "oci_identity_availability_domains" "ads" {
  compartment_id = var.compartment_ocid
}

data "oci_core_images" "ubuntu_arm" {
  compartment_id           = var.compartment_ocid
  operating_system         = "Canonical Ubuntu"
  operating_system_version = "24.04"
  shape                    = "VM.Standard.A1.Flex"
  sort_by                  = "TIMECREATED"
  sort_order               = "DESC"
}

data "oci_core_images" "ubuntu_amd" {
  compartment_id           = var.compartment_ocid
  operating_system         = "Canonical Ubuntu"
  operating_system_version = "24.04"
  shape                    = "VM.Standard.E2.1.Micro"
  sort_by                  = "TIMECREATED"
  sort_order               = "DESC"
}

# ---------- Minecraft サーバー (Arm) ----------

resource "oci_core_instance" "mc_server" {
  compartment_id      = var.compartment_ocid
  availability_domain = data.oci_identity_availability_domains.ads.availability_domains[var.ad_index].name
  display_name        = "mc-server"
  shape               = "VM.Standard.A1.Flex"

  # Always Free の Arm 枠は合計 2 OCPU / 12GB (2026-06-15 に 4/24 から半減)。ここで全量を使う。
  shape_config {
    ocpus         = 2
    memory_in_gbs = 12
  }

  source_details {
    source_type             = "image"
    source_id               = data.oci_core_images.ubuntu_arm.images[0].id
    boot_volume_size_in_gbs = 100
  }

  create_vnic_details {
    subnet_id        = oci_core_subnet.public.id
    private_ip       = var.mc_private_ip
    assign_public_ip = true
    nsg_ids          = [oci_core_network_security_group.minecraft.id]
    hostname_label   = "mcserver"
  }

  metadata = {
    ssh_authorized_keys = var.ssh_public_key
    user_data = base64encode(templatefile("${path.module}/cloud-init/mc-server.yaml.tftpl", {
      exposure_mode       = var.exposure_mode
      subnet_cidr         = var.subnet_cidr
      mc_private_ip       = var.mc_private_ip
      tailscale_authkey   = var.tailscale_authkey_server
      install_zerotier    = local.install_zerotier
      zerotier_network_id = var.zerotier_network_id
      enable_oci_backup   = var.enable_oci_backup
      docker_compose      = local.docker_compose
      mc_env              = local.mc_env
      backup_sh           = local.backup_sh
      rclone_conf         = local.rclone_conf
      playit_check        = local.playit_check
    }))
  }

  # CPU / メモリ / ディスク / ネットワークのメトリクスはこのプラグインが収集する。
  # monitor.py を止めてもこちらは動き続ける。
  agent_config {
    plugins_config {
      name          = "Compute Instance Monitoring"
      desired_state = "ENABLED"
    }
  }

  lifecycle {
    # metadata を無視しているのは事故防止。user_data の変更は
    # インスタンス置換 = ブートボリューム破棄 = ワールド消失を招く。
    # 稼働後の変更は Ansible (site.yml -t app) を通す。
    # 意図的に作り直す場合は `terraform apply -replace=oci_core_instance.mc_server`。
    # source_id はイメージが更新されるたびに差分が出るため無視する。
    ignore_changes = [metadata, source_details[0].source_id]
  }
}

# ---------- 監視サーバー (AMD Micro) ----------

resource "oci_core_instance" "mc_monitor" {
  compartment_id      = var.compartment_ocid
  availability_domain = data.oci_identity_availability_domains.ads.availability_domains[var.ad_index].name
  display_name        = "mc-monitor"
  shape               = "VM.Standard.E2.1.Micro"

  source_details {
    source_type             = "image"
    source_id               = data.oci_core_images.ubuntu_amd.images[0].id
    boot_volume_size_in_gbs = 50
  }

  create_vnic_details {
    subnet_id        = oci_core_subnet.public.id
    private_ip       = var.monitor_private_ip
    assign_public_ip = true
    nsg_ids          = [oci_core_network_security_group.monitor.id]
    hostname_label   = "mcmonitor"
  }

  metadata = {
    ssh_authorized_keys = var.ssh_public_key
    user_data = base64encode(templatefile("${path.module}/cloud-init/mc-monitor.yaml.tftpl", {
      tailscale_authkey    = var.tailscale_authkey_monitor
      install_zerotier     = local.install_zerotier
      zerotier_network_id  = var.zerotier_network_id
      enable_monitor_timer = var.enable_monitor_timer
      monitor_env          = local.monitor_env
      monitor_py           = local.monitor_py
      requirements_txt     = local.requirements_txt
      monitor_service      = local.monitor_service
      monitor_timer        = local.monitor_timer
    }))
  }

  # 監視VM自身のメトリクスも取る。docs/manual/05-dashboard.md の
  # 「mc-server と mc-monitor の比較表示」に必要。
  agent_config {
    plugins_config {
      name          = "Compute Instance Monitoring"
      desired_state = "ENABLED"
    }
  }

  lifecycle {
    ignore_changes = [metadata, source_details[0].source_id]
  }
}
