# 25565 の ingress ルールはどの exposure_mode でも作らない。
# playit / Tailscale / ZeroTier はいずれも VM 側から張ったアウトバウンド接続を
# 使い回す方式なので、受信の口を開ける必要がない。
# 設計の根拠は docs/spec/03-network-security.md を参照。

resource "oci_core_vcn" "main" {
  compartment_id = var.compartment_ocid
  cidr_blocks    = [var.vcn_cidr]
  display_name   = "vcn-minecraft"
  dns_label      = "mcvcn"
}

resource "oci_core_internet_gateway" "main" {
  compartment_id = var.compartment_ocid
  vcn_id         = oci_core_vcn.main.id
  display_name   = "igw-minecraft"
  enabled        = true
}

resource "oci_core_route_table" "public" {
  compartment_id = var.compartment_ocid
  vcn_id         = oci_core_vcn.main.id
  display_name   = "rt-public"

  route_rules {
    destination       = "0.0.0.0/0"
    destination_type  = "CIDR_BLOCK"
    network_entity_id = oci_core_internet_gateway.main.id
  }
}

# ingress 制御は NSG に一本化。セキュリティリストは egress のみ許可し、
# 2箇所で許可/拒否を管理しないようにする。
resource "oci_core_security_list" "minimal" {
  compartment_id = var.compartment_ocid
  vcn_id         = oci_core_vcn.main.id
  display_name   = "sl-minimal"

  egress_security_rules {
    destination      = "0.0.0.0/0"
    destination_type = "CIDR_BLOCK"
    protocol         = "all"
  }
}

resource "oci_core_subnet" "public" {
  compartment_id             = var.compartment_ocid
  vcn_id                     = oci_core_vcn.main.id
  cidr_block                 = var.subnet_cidr
  display_name               = "subnet-public"
  dns_label                  = "public"
  route_table_id             = oci_core_route_table.public.id
  security_list_ids          = [oci_core_security_list.minimal.id]
  prohibit_public_ip_on_vnic = false
}

# ---------- NSG: Minecraft サーバー ----------

resource "oci_core_network_security_group" "minecraft" {
  compartment_id = var.compartment_ocid
  vcn_id         = oci_core_vcn.main.id
  display_name   = "nsg-minecraft"
}

# RCON: 監視VMからのみ。Tailscale を経由せず VCN 内で閉じる
resource "oci_core_network_security_group_security_rule" "mc_in_rcon" {
  network_security_group_id = oci_core_network_security_group.minecraft.id
  direction                 = "INGRESS"
  protocol                  = "6"
  source                    = "${var.monitor_private_ip}/32"
  source_type               = "CIDR_BLOCK"
  description               = "RCON from monitor VM only"

  tcp_options {
    destination_port_range {
      min = 25575
      max = 25575
    }
  }
}

# 初回構築時のみ。Tailscale 疎通確認後に enable_home_ssh=false で閉じる
resource "oci_core_network_security_group_security_rule" "mc_in_ssh" {
  count                     = var.enable_home_ssh ? 1 : 0
  network_security_group_id = oci_core_network_security_group.minecraft.id
  direction                 = "INGRESS"
  protocol                  = "6"
  source                    = var.home_ip_cidr
  source_type               = "CIDR_BLOCK"
  description               = "SSH from home (bootstrap only)"

  tcp_options {
    destination_port_range {
      min = 22
      max = 22
    }
  }
}

resource "oci_core_network_security_group_security_rule" "mc_out" {
  network_security_group_id = oci_core_network_security_group.minecraft.id
  direction                 = "EGRESS"
  protocol                  = "all"
  destination               = "0.0.0.0/0"
  destination_type          = "CIDR_BLOCK"
  description               = "All outbound (tunnels, updates, backups)"
}

# ---------- NSG: 監視サーバー ----------

resource "oci_core_network_security_group" "monitor" {
  compartment_id = var.compartment_ocid
  vcn_id         = oci_core_vcn.main.id
  display_name   = "nsg-monitor"
}

resource "oci_core_network_security_group_security_rule" "mon_in_ssh" {
  count                     = var.enable_home_ssh ? 1 : 0
  network_security_group_id = oci_core_network_security_group.monitor.id
  direction                 = "INGRESS"
  protocol                  = "6"
  source                    = var.home_ip_cidr
  source_type               = "CIDR_BLOCK"
  description               = "SSH from home (bootstrap only)"

  tcp_options {
    destination_port_range {
      min = 22
      max = 22
    }
  }
}

resource "oci_core_network_security_group_security_rule" "mon_out" {
  network_security_group_id = oci_core_network_security_group.monitor.id
  direction                 = "EGRESS"
  protocol                  = "all"
  destination               = "0.0.0.0/0"
  destination_type          = "CIDR_BLOCK"
  description               = "All outbound (RCON, Monitoring API, Discord)"
}
