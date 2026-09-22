<!-- このページは docs/spec/08-parameters.md から生成しています。直接編集しないでください。
     修正は docs/spec/ 側に入れて `python scripts/sync-wiki.py` を実行してください。 -->

# 08. パラメータ一覧

`terraform/variables.tf` で宣言している変数と、そこから生成される `.env` の変数を列挙する。

サンプルは [terraform/terraform.tfvars_sample](../blob/main/terraform/terraform.tfvars_sample)。値の取得手順は [docs/manual/01-prerequisites.md](../blob/main/docs/manual/01-prerequisites.md) にある。

`scripts/check-consistency.py` が「宣言した変数がサンプルに載っているか」「monitor.py が読む変数がテンプレートとサンプルの両方にあるか」を検査する。

## 凡例

| 記号 | 意味 |
| --- | --- |
| **必須** | 既定値がない。`terraform.tfvars` に書かないと apply できない |
| 秘 | `sensitive = true`。plan/apply の出力に表示されない |

## Terraform 変数

### OCI テナンシー

| 変数 | 既定 | 秘 | 入手元 |
| --- | --- | --- | --- |
| `tenancy_ocid` | **必須** | | コンソール → プロフィール → テナンシー |
| `compartment_ocid` | **必須** | | `oci iam compartment list --all` |
| `region` | `ap-tokyo-1` | | - |
| `ad_index` | `0` | | Out of Capacity 時に 1, 2 を試す |

`tenancy_ocid` と `compartment_ocid` を分けているのは、動的グループとポリシーがテナンシールートにしか作れないためである。ルートコンパートメントを使う場合は同じ値になる。

### ネットワーク

| 変数 | 既定 | 秘 | 備考 |
| --- | --- | --- | --- |
| `vcn_cidr` | `10.0.0.0/16` | | 通常は変更不要 |
| `subnet_cidr` | `10.0.1.0/24` | | iptables の RCON 許可範囲にも使われる |
| `mc_private_ip` | `10.0.1.10` | | RCON の接続先。`monitor.env` の `RCON_HOST` になる |
| `monitor_private_ip` | `10.0.1.20` | | NSG の RCON 許可元 |

### SSH

| 変数 | 既定 | 秘 | 入手元 / 備考 |
| --- | --- | --- | --- |
| `ssh_public_key` | **必須** | | `cat ~/.ssh/oci_mc.pub` |
| `enable_home_ssh` | `true` | | Tailscale 疎通後に `false` へ |
| `home_ip_cidr` | `""` | | `curl -s https://ifconfig.me` + `/32` |

`enable_home_ssh = true` かつ `home_ip_cidr` が空だと validation で弾かれる。

### オーバーレイネットワーク

| 変数 | 既定 | 秘 | 入手元 / 備考 |
| --- | --- | --- | --- |
| `tailscale_authkey_server` | **必須** | 秘 | 管理画面 → Settings → Keys。**Tags に `tag:mc-server` を指定して発行** |
| `tailscale_authkey_monitor` | **必須** | 秘 | 同上。Tags は `tag:mc-monitor` |
| `enable_zerotier` | `false` | | Tailscale と併設して予備経路にする |
| `zerotier_network_id` | `""` | | my.zerotier.com の16桁ネットワークID |

`enable_zerotier = true` または `exposure_mode = "zerotier"` のとき `zerotier_network_id` は必須 (validation)。

### 公開方式

| 変数 | 既定 | 秘 | 備考 |
| --- | --- | --- | --- |
| `exposure_mode` | `playit` | | `playit` / `tailscale` / `zerotier` (validation) |
| `playit_secret_key` | `""` | 秘 | 既定は空だが、空のままだと playit コンテナが exit 1 する。playit.gg の docker 向けセットアップウィザードで先に発行する |

### Minecraft サーバー

| 変数 | 既定 | 秘 | 備考 |
| --- | --- | --- | --- |
| `rcon_password` | **必須** | 秘 | `openssl rand -base64 24` |
| `mc_memory` | `8G` | | 12GB の VM に対して 8G。残りは OS とページキャッシュ |
| `mc_motd` | `OCI Minecraft Server` | | |
| `mc_difficulty` | `normal` | | |
| `mc_max_players` | `20` | | ダッシュボードのゲージ上限にも対応させる |
| `mc_view_distance` | `8` | | |
| `mc_simulation_distance` | `6` | | |
| `mc_whitelist` | `[]` | | **空だとホワイトリスト無効**。MCID のリスト |
| `mc_ops` | `[]` | | OP を与える MCID のリスト |
| `mc_plugins` | `["8631","28140"]` | | SpigotMC のリソースID |

### mc-router (`exposure_mode = "playit"` のときのみ)

| 変数 | 既定 | 秘 | 備考 |
| --- | --- | --- | --- |
| `mc_router_rate_limit` | `5` | | 1秒あたりの接続数の上限。小さすぎると正当な再接続が弾かれる |
| `mc_router_auto_scale` | `false` | | 無人時に mc を停止する。有効にすると監視が誤報し `backup.sh` が実行できなくなる |
| `mc_router_scale_down_after` | `"30m"` | | `mc_router_auto_scale = true` のときのみ有効 |

### 監視

| 変数 | 既定 | 秘 | 入手元 / 備考 |
| --- | --- | --- | --- |
| `discord_webhook_url` | **必須** | 秘 | Discord → チャンネル編集 → 連携サービス → ウェブフック |
| `filesystem_name` | `/` | | **構築後に実測値へ修正する** (V-08) |
| `monitor_thresholds` | cpu/memory 85, disk 80, tps 15 | | オブジェクト型 |
| `enable_monitor_timer` | `true` | | `filesystem_name` 未確定のうちは `false` でもよい |
| `enable_game_log_collection` | `false` | | OCI Logging + Unified Monitoring Agent でゲームログ(join/leave等)を収集する |

### バックアップ

| 変数 | 既定 | 秘 | 入手元 / 備考 |
| --- | --- | --- | --- |
| `r2_access_key_id` | **必須** | 秘 | R2 → R2 APIトークンの管理 |
| `r2_secret_access_key` | **必須** | 秘 | 同上 (再表示されない) |
| `r2_endpoint` | **必須** | | `https://<account-id>.r2.cloudflarestorage.com` |
| `r2_bucket` | `minecraft-backup` | | R2 側で事前に作成しておく |
| `enable_oci_backup` | `true` | | OCI Object Storage への二次コピー |
| `backup_bucket_name` | `minecraft-backup` | | Terraform が作成する |
| `backup_keep_generations` | `7` | | VM 上に残す世代数。0 で無制限 |
| `backup_remote_keep_days` | `30` | | クラウド側の保持日数。0 で無期限 |

## `.env` として VM に配置される変数

実体は Terraform のテンプレートが生成し、cloud-init が配置する。サンプルは参照用・手動フォールバック用。

### mc-server: `/home/ubuntu/minecraft/.env` (0600)

生成元: [terraform/templates/mc-server.env.tftpl](../blob/main/terraform/templates/mc-server.env.tftpl) / サンプル: [env/mc-server.env_sample](../blob/main/env/mc-server.env_sample)

| 変数 | 由来 | 読む主体 |
| --- | --- | --- |
| `RCON_PASSWORD` | `var.rcon_password` | docker compose の変数展開、`backup.sh` |
| `PLAYIT_SECRET_KEY` | `var.playit_secret_key` | docker compose の変数展開経由で playit-agent コンテナの `SECRET_KEY` に渡る |

### mc-monitor: `/home/ubuntu/.env` (0600)

生成元: [terraform/templates/mc-monitor.env.tftpl](../blob/main/terraform/templates/mc-monitor.env.tftpl) / サンプル: [env/mc-monitor.env_sample](../blob/main/env/mc-monitor.env_sample)

| 変数 | 由来 | 必須 |
| --- | --- | --- |
| `DISCORD_WEBHOOK_URL` | `var.discord_webhook_url` | ○ |
| `RCON_HOST` | `var.mc_private_ip` | ○ |
| `RCON_PORT` | `25575` (固定) | 既定 25575 |
| `RCON_PASSWORD` | `var.rcon_password` | ○ |
| `ARM_INSTANCE_OCID` | `oci_core_instance.mc_server.id` | ○ |
| `COMPARTMENT_OCID` | `var.compartment_ocid` | ○ |
| `FILESYSTEM_NAME` | `var.filesystem_name` | 既定 `/` |
| `THRESHOLD_CPU` / `_MEMORY` / `_DISK` / `_TPS` | `var.monitor_thresholds` | 既定あり |

monitor.py はこれ以外に `STATE_FILE` と `CUSTOM_NAMESPACE` も任意で受け付ける (既定は `/home/ubuntu/monitor_state.json` と `custom_minecraft`)。テンプレートでは生成していない。

### mc-server: `/home/ubuntu/.config/rclone/rclone.conf` (0600)

生成元: [terraform/templates/rclone.conf.tftpl](../blob/main/terraform/templates/rclone.conf.tftpl) / サンプル: [env/rclone.conf_sample](../blob/main/env/rclone.conf_sample)

`r2_access_key_id` / `r2_secret_access_key` / `r2_endpoint` から生成する。`region = auto` と `no_check_bucket = true` は R2 固有の設定で、後者を付けないと PutObject が 501 を返すことがある。

## Terraform 出力

| 出力 | 用途 |
| --- | --- |
| `minecraft_public_ip` / `monitor_public_ip` | 初回構築時のフォールバック SSH。穴を閉じた後は到達しない |
| `ssh_bootstrap_minecraft` / `ssh_bootstrap_monitor` | 上記の ssh コマンド |
| `minecraft_instance_ocid` / `monitor_instance_ocid` | ダッシュボードの MQL |
| `backup_bucket` | `<namespace>/<bucket>` |
| `exposure_mode` | 現在の公開方式 |
| `minecraft_connect_address` | プレイヤーに渡す接続先の案内 |
| `dashboard_mql` | 各ウィジェット用の MQL (OCID 埋め込み済み) |

## 設定できないもの (ハードコード)

変数化していない値と、その理由。

| 値 | 場所 | 変数化していない理由 |
| --- | --- | --- |
| Terraform のバージョン | `terraform/.terraform-version` | tenv が読む固定ファイル。変数ではない ([A2. ツール導入](Spec-A2-toolchain)) |
| Python 依存のバージョン | `monitor/requirements.txt` (生成物) | `pyproject.toml` から `uv pip compile` で生成する。手で編集しない |
| RCON ポート 25575 | 複数箇所 | 変える理由がない。変えると NSG / iptables / .env の3箇所に影響する |
| Minecraft ポート 25565 | 同上 | 同上。クライアントの既定値 |
| shape と OCPU/メモリ (2/12) | `compute.tf` | Always Free 枠の上限に張り付いている |
| ブートボリューム 100GB / 50GB | `compute.tf` | 同上 |
| `TYPE=PAPER` | compose テンプレート | 他の種別に変えると設定全体の前提が変わる |
| `VERSION=LATEST` | compose テンプレート | 固定したい場合は [07. 構成技術・バージョン](Spec-07-tech-stack) 参照 |
| Tailscale のホスト名とタグ | cloud-init | ACL と1対1で対応している |
| 監視間隔 5 分 | `monitor/systemd/mc-monitor.timer` | unit ファイルを直接編集する |
