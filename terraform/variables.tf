# 全変数の一覧・入手元・秘匿区分は docs/spec/08-parameters.md にまとめてある。

# ---------- OCI テナンシー ----------

variable "region" {
  type    = string
  default = "ap-tokyo-1"
}

variable "tenancy_ocid" {
  type        = string
  description = <<-EOT
    テナンシーのOCID。動的グループとポリシーはテナンシールートにしか
    作成できないため、compartment_ocid とは別に必要。
    コンソール → プロフィール → テナンシー で取得。
  EOT
}

variable "compartment_ocid" {
  type        = string
  description = "リソースを作成するコンパートメントのOCID"
}

variable "ad_index" {
  type        = number
  default     = 0
  description = "Availability Domain のインデックス。Out of Capacity 時に変更"
}

# ---------- ネットワーク ----------

variable "vcn_cidr" {
  type    = string
  default = "10.0.0.0/16"
}

variable "subnet_cidr" {
  type    = string
  default = "10.0.1.0/24"
}

variable "mc_private_ip" {
  type    = string
  default = "10.0.1.10"
}

variable "monitor_private_ip" {
  type    = string
  default = "10.0.1.20"
}

# ---------- SSH ----------

variable "ssh_public_key" {
  type        = string
  description = "SSH公開鍵の中身。Tailscale SSH が主だが初回構築のフォールバックに使う"
}

variable "enable_home_ssh" {
  type        = bool
  default     = true
  description = "初回構築時のSSH穴。Tailscale疎通確認後に false へ"
}

variable "home_ip_cidr" {
  type        = string
  default     = ""
  description = "自宅グローバルIP (例: 203.0.113.5/32)"

  validation {
    condition     = var.home_ip_cidr == "" || can(cidrhost(var.home_ip_cidr, 0))
    error_message = "home_ip_cidr は CIDR 表記 (例: 203.0.113.5/32) で指定してください。"
  }

  validation {
    # 空のまま enable_home_ssh=true にすると NSG ルールの source が不正になり
    # apply が中途で失敗する。先に弾く。
    # (変数をまたぐ validation は Terraform 1.9 以降の機能)
    condition     = !var.enable_home_ssh || var.home_ip_cidr != ""
    error_message = "enable_home_ssh = true のときは home_ip_cidr が必須です。`curl -s https://ifconfig.me` で確認してください。"
  }
}

# ---------- オーバーレイネットワーク ----------

variable "tailscale_authkey_server" {
  type        = string
  sensitive   = true
  description = <<-EOT
    mc-server 用の Auth Key。`tag:mc-server` のタグ権限を付けて発行する。
    タグなしのキーで参加すると ACL の tag:mc-server が付かず、
    SSH ポリシーが効かない (docs/manual/02b-tailscale-acl.md 参照)。
  EOT
}

variable "tailscale_authkey_monitor" {
  type        = string
  sensitive   = true
  description = "mc-monitor 用の Auth Key。`tag:mc-monitor` のタグ権限を付けて発行する"
}

variable "enable_zerotier" {
  type        = bool
  default     = false
  description = <<-EOT
    ZeroTier を Tailscale と併設する。exposure_mode とは独立。
    Tailscale 障害時の予備経路、または友人にアカウント作成をさせたくない
    場合の接続手段として使う。
  EOT
}

variable "zerotier_network_id" {
  type        = string
  default     = ""
  description = "ZeroTier の16桁ネットワークID。enable_zerotier=true か exposure_mode=zerotier のとき必須"

  validation {
    condition     = var.zerotier_network_id == "" || can(regex("^[0-9a-f]{16}$", var.zerotier_network_id))
    error_message = "zerotier_network_id は16桁の16進数で指定してください。"
  }

  validation {
    condition     = !(var.enable_zerotier || var.exposure_mode == "zerotier") || var.zerotier_network_id != ""
    error_message = "enable_zerotier = true または exposure_mode = \"zerotier\" のときは zerotier_network_id が必須です。"
  }
}

# ---------- Minecraft の公開方式 ----------

variable "exposure_mode" {
  type        = string
  default     = "playit"
  description = <<-EOT
    Minecraft の公開方式。どれを選んでも 25565 の ingress は開けない。
      playit    : playit.gg のトンネル経由。友人側の準備が不要
      tailscale : tailnet 内のみ。tailscale0 経由の 25565 だけ許可
      zerotier  : ZeroTier ネットワーク内のみ。zt+ 経由の 25565 だけ許可
    比較と選定理由は docs/spec/02-architecture.md を参照。
  EOT

  validation {
    condition     = contains(["playit", "tailscale", "zerotier"], var.exposure_mode)
    error_message = "exposure_mode は playit / tailscale / zerotier のいずれかです。"
  }
}

variable "playit_secret_key" {
  type        = string
  sensitive   = true
  default     = ""
  description = <<-EOT
    playit.gg のシークレットキー。初回構築時は空でよい。
    `docker compose run --rm playit` で認証URLを開いて紐付けた後に
    ダッシュボードから取得し、Ansible の app タグで配送する。
  EOT
}

# ---------- Minecraft サーバー設定 ----------

variable "mc_memory" {
  type        = string
  default     = "8G"
  description = "JVM ヒープ。12GB の VM に対して 8G。残りは OS とページキャッシュ用"
}

variable "mc_motd" {
  type    = string
  default = "OCI Minecraft Server"
}

variable "mc_difficulty" {
  type    = string
  default = "normal"
}

variable "mc_max_players" {
  type    = number
  default = 20
}

variable "mc_view_distance" {
  type    = number
  default = 8
}

variable "mc_simulation_distance" {
  type    = number
  default = 6
}

variable "mc_whitelist" {
  type        = list(string)
  default     = []
  description = <<-EOT
    許可する Minecraft ID のリスト。空だとホワイトリストを無効化する。
    Tailscale ACL はIPしか見ないため、MCID単位の制御はここが担う
    (docs/spec/03-network-security.md 参照)。
  EOT
}

variable "mc_ops" {
  type        = list(string)
  default     = []
  description = "OP を与える Minecraft ID のリスト"
}

variable "mc_plugins" {
  type        = list(string)
  default     = ["8631", "28140"] # CoreProtect, LuckPerms
  description = <<-EOT
    導入するプラグインの SpigotMC リソースID (SPIGET_RESOURCES)。
    既定は CoreProtect(8631) と LuckPerms(28140)。
    IDとプラグインの対応は docs/spec/07-tech-stack.md にある。
  EOT
}

variable "rcon_password" {
  type        = string
  sensitive   = true
  description = "`openssl rand -base64 24` で生成した値"
}

# ---------- mc-router (exposure_mode = playit のときのみ) ----------

variable "mc_router_rate_limit" {
  type        = number
  default     = 5
  description = <<-EOT
    mc-router が受け付ける1秒あたりの接続数 (CONNECTION_RATE_LIMIT)。
    mc-router 自体の既定は 1 で、再接続の連打でも弾かれるため 5 にしている。
    小さすぎると正当な再接続が失敗し、原因の分かりにくい接続不良になる。
  EOT
}

variable "mc_router_auto_scale" {
  type        = bool
  default     = false
  description = <<-EOT
    誰も繋いでいない間 mc コンテナを停止する (mc-router の scale to zero)。
    有効にすると mc-router に docker.sock を渡すことになる (= ホスト root 相当)。

    既定を false にしているのは、停止中は次の2つが成立しなくなるため。
      - monitor.py は RCON 直結なので「意図的な停止」と「落ちた」を区別できず、
        Discord に誤報を出す (docs/spec/04-monitoring.md)
      - backup.sh は `--network container:mc` で RCON に繋ぐため実行できない
        (起動していなければ止まるようガードを入れてある)
    Always Free の VM は止めても課金が減らないため、有効化の利点はメモリの解放だけ。
  EOT
}

variable "mc_router_scale_down_after" {
  type        = string
  default     = "30m"
  description = "最後のプレイヤーが抜けてから mc を停止するまでの時間。mc_router_auto_scale = true のときのみ有効"
}

# ---------- 監視 ----------

variable "discord_webhook_url" {
  type      = string
  sensitive = true
}

variable "filesystem_name" {
  type        = string
  default     = "/"
  description = <<-EOT
    FilesystemUtilization の fileSystemName ディメンションの実測値。
    `/` ではなく `/dev/sda1` のようなデバイス名のことがある。
    構築後にメトリクス・エクスプローラで確認して修正する
    (docs/manual/02-post-setup.md 手順8)。
  EOT
}

variable "monitor_thresholds" {
  type = object({
    cpu    = number
    memory = number
    disk   = number
    tps    = number
  })
  default = {
    cpu    = 85.0
    memory = 85.0
    disk   = 80.0
    tps    = 15.0
  }
  description = "アラート閾値。cpu/memory/disk は以上で発火、tps は未満で発火"
}

variable "enable_monitor_timer" {
  type        = bool
  default     = true
  description = <<-EOT
    mc-monitor.timer を初回構築時から有効にする。
    filesystem_name が未確定のうちに誤検知させたくない場合は false にし、
    確認後に true で再 apply する (または Ansible の monitor タグで有効化)。
  EOT
}

# ---------- バックアップ ----------

variable "r2_access_key_id" {
  type      = string
  sensitive = true
}

variable "r2_secret_access_key" {
  type      = string
  sensitive = true
}

variable "r2_endpoint" {
  type        = string
  description = "https://<account-id>.r2.cloudflarestorage.com"
}

variable "r2_bucket" {
  type    = string
  default = "minecraft-backup"
}

variable "enable_oci_backup" {
  type        = bool
  default     = true
  description = <<-EOT
    R2 に加えて OCI Object Storage にも同じバックアップを置く。
    事業者を分けた一次コピーが R2、同一事業者内の二次コピーが OCI。
    設計上の位置づけは docs/spec/05-backup.md を参照。
  EOT
}

variable "backup_bucket_name" {
  type    = string
  default = "minecraft-backup"
}

variable "backup_keep_generations" {
  type        = number
  default     = 7
  description = "ローカル (VM 上) に保持する世代数。100GB のブートボリュームに収まる範囲で"
}

variable "backup_remote_keep_days" {
  type        = number
  default     = 30
  description = <<-EOT
    クラウド側 (R2 / OCI) の保持日数。0 で無期限。
    R2 は backup.sh の `rclone delete --min-age`、
    OCI は storage.tf のライフサイクルポリシーがそれぞれ削除する。
  EOT
}
