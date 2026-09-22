<!-- このページは docs/spec/02-architecture.md から生成しています。直接編集しないでください。
     修正は docs/spec/ 側に入れて `python scripts/sync-wiki.py` を実行してください。 -->

# 02. アーキテクチャ

## 全体構成

```text
                    [インターネット]
                          │
                          │ すべてアウトバウンド接続のみ
                          │ (受信ポートの開放なし)
                          ▼
        ┌─────────────────┴─────────────────┐
        │                                   │
  [Tailscale]                        [playit.gg]
   SSH/管理 (常時)                    Minecraft接続
   + Minecraft接続                    (exposure_mode=playit)
   (exposure_mode=tailscale)          │
        │                             │
        └─────────────────┬───────────┘
                          ▼
┌───────────────────────────────────────────────┐
│  OCI VCN 10.0.0.0/16                          │
│  Public Subnet 10.0.1.0/24                    │
│                                               │
│  ┌──────────────────────┐  ┌────────────────┐ │
│  │ mc-server (Arm)      │  │ mc-monitor     │ │
│  │ 10.0.1.10            │◄─┤ 10.0.1.20      │ │
│  │ 2 OCPU / 12GB / 100GB│  │ AMD Micro      │ │
│  │                      │  │ 1/8 OCPU / 1GB │ │
│  │ - PaperMC (Docker)   │  │                │ │
│  │ - mc-router ※        │  │                │ │
│  │ - Tailscale (SSH)    │  │ - monitor.py   │ │
│  │ - playit agent ※     │  │   (5分ごと)    │ │
│  │ - backup.sh (手動)   │  │ - Tailscale    │ │
│  └──────────────────────┘  └────────────────┘ │
│         RCON 25575 ◄─────────────┘            │
└───────────────────────────────────────────────┘
        │              │               │
        ▼              ▼               ▼
  [Cloudflare R2]  [OCI Object    [OCI Monitoring]
   一次コピー       Storage]         │        │
                    二次コピー  [Dashboards] [Discord]
```

※ `exposure_mode = playit` のときのみ

## コンポーネントの責務

| コンポーネント | 責務 | 実装 |
| --- | --- | --- |
| mc-server | Minecraft の実行、バックアップの生成と転送 | `terraform/compute.tf` の `mc_server` |
| mc-router | playit からの接続を受けて mc に中継し、接続レートを絞る | `docker-compose.yml.tftpl` (`exposure_mode=playit` のみ) |
| mc-monitor | メトリクスの読み取り・判定・通知・記録 | `terraform/compute.tf` の `mc_monitor` |
| NSG | ingress 制御の一元管理 | `terraform/network.tf` |
| iptables (VM内) | オーバーレイ経由の 25565 だけを通す | cloud-init の `runcmd` |
| Tailscale | 管理 SSH と、方式Bでの Minecraft 接続 | cloud-init + `tailscale/acl.hujson` |
| Oracle Cloud Agent | CPU / メモリ / ディスク / NW のメトリクス収集 | `agent_config` (両VM) |
| monitor.py | TPS / プレイヤー数 / 死活の取得と Discord 通知 | `monitor/monitor.py` |
| OCI Monitoring | メトリクスの保管とクエリ | 標準 + `custom_minecraft` |
| R2 / OCI Object Storage | バックアップの保全 | `backup.sh` + `terraform/storage.tf` |

### なぜ監視を別VMに置くのか

mc-server 自身に監視を置くと、サーバーごと落ちた時に「落ちたこと」を通知できない。AMD Micro は Always Free 枠で2台使えるため、1台を監視専用に充てるコストはゼロである。

### なぜ Discord 通知を VM から直接投げるのか

OCI Notifications に Discord 連携がなく、間に OCI Functions を挟む必要がある。Functions が Always Free 対象かは公式一覧に明記されていないため、課金リスクを避けて monitor.py から直接 Webhook を叩く。OCI 標準アラームはメール通知のみの保険として併用できる ([04. 監視](Spec-04-monitoring))。

### なぜ VictoriaMetrics や Grafana を常駐させないのか

別リポジトリの Grafana + VictoriaMetrics + node_exporter を常駐させる構成 (旧 `monitor_sample/`、削除済み) は Raspberry Pi の自宅環境では妥当だが、本構成では次の理由で採らない。

- CPU / メモリ / ディスクは Oracle Cloud Agent が**追加実装なしで**収集している
- 1GB メモリの監視VMに時系列DBと Grafana を同居させると余裕がない
- 可視化は OCI Console Dashboards で足りる

ただしダッシュボードの**パネル構成は参考にしている** (対応表は `dashboards/oci-dashboard.json` の `grafana_equivalent`)。

### セルフホスト構成から何を取り込んだか

自宅 Raspberry Pi 向けのセルフホスト構成 (Pi 側の compose と、別PCで Grafana を動かす compose の2環境) を突き合わせ、**OCI 側のマネージドサービスや既存実装で実現済みのものは作らない**方針で選別した。結果として取り込んだコンテナは mc-router だけである。

| セルフホスト側のコンテナ | 本構成での扱い | 理由 |
| --- | --- | --- |
| `papermc` | `mc` として既存 | - |
| `playit` | 既存 (タグ 1.0 固定) | - |
| **`mc-router`** | **取り込む** | **OCI 側に相当するものがない** |
| `backup` (`itzg/mc-backup`) | 作らない | `backup.sh` が同じイメージを都度 `docker run` し、R2 と OCI Object Storage の2系統に置いている ([05. バックアップ](Spec-05-backup)) |
| `mc-monitor` exporter | 作らない | `monitor.py` が RCON で TPS・人数・死活を取り `custom_minecraft` に記録する ([04. 監視](Spec-04-monitoring)) |
| `node-exporter` | 作らない | Oracle Cloud Agent が CPU / メモリ / ディスク / NW を追加実装なしで収集する |
| `victoriametrics` | 作らない | OCI Monitoring が保管とクエリを担う |
| `loki` / `promtail` | 作らない | 代わりに OCI Logging + Unified Monitoring Agent を使う (`enable_game_log_collection`、既定は無効。[04. 監視](Spec-04-monitoring)) |
| `grafana` (別PC側) | 作らない | 可視化は OCI Console Dashboards |

セルフホスト側の設定のうち、コンテナ本体ではない運用品質の部分 (`stop_grace_period`、ログローテーションの上限、`no-new-privileges`) は取り込んでいる。

### なぜ mc-router を挟むのか

playit.gg のアドレスは知っていれば誰でも接続を試せるため、接続の連打が PaperMC 本体に素通りする。mc-router の `CONNECTION_RATE_LIMIT` (既定 5/秒) をその前段に置く。ホワイトリスト ([03. ネットワーク・セキュリティ](Spec-03-network-security) の層4) はログイン試行そのものは止められないので、この層とは役割が違う。

`exposure_mode = tailscale` / `zerotier` では入れない。到達できるのはオーバーレイの参加者だけで、mc-router を入れるとバックエンド検出のために `mc` を bridge に移す必要が生じ、Docker の DNAT が `INPUT` チェーンを通らないせいで**層3 (インターフェース判定) の iptables が効かなくなる**ためである。

mc-router は同じ bridge の中だけで待ち受け、25565 をホストに出さない。`mc_router_auto_scale = false` (既定) では Docker API を使わないため `docker.sock` も渡さない。

### scale to zero を既定で無効にしている理由

mc-router は「誰かが繋いだら起動し、全員抜けたら停止する」ことができる (`mc_router_auto_scale`)。既定で無効にしているのは次の3点による。

- Always Free の VM は止めても課金が減らない。得られるのはメモリの解放だけである
- `monitor.py` は RCON 直結なので「意図的な停止」と「落ちた」を区別できず、Discord に誤報が出る
- `backup.sh` は `--network container:mc` で RCON に繋ぐため、停止中は実行できない

有効化すると mc-router に `docker.sock` を渡すことになり、ホスト root 相当の権限を持つコンテナが1つ増える点も含めて判断する。

## 構成管理: Terraform 主体 / Ansible 最小

### 境界の判断基準

判断基準は **「VM を作り直さずに変更したいか」** の一点である。

OCI では `metadata.user_data` の変更がインスタンス置換を引き起こす。置換はブートボリュームの破棄を意味し、**ワールドが消える**。したがって頻繁に変わる値を cloud-init だけに置くことはできない。

| | 担当 | 対象 |
| --- | --- | --- |
| 初回構築で確定し、以後変わらない | **Terraform + cloud-init** | apt、SSH パスワード認証無効化、Tailscale/ZeroTier 参加、iptables、Docker、ディレクトリ構成、venv、systemd unit、rclone.conf、backup.sh、playit-check.sh、unattended-upgrades、**初回の docker-compose.yml と .env** |
| 稼働後に繰り返し変える | **Ansible (最小)** | ① `monitor.py` と閾値・`FILESYSTEM_NAME` ② `docker-compose.yml` と `.env` (playit キー、ホワイトリスト、プラグイン、MEMORY) |

`terraform apply` の時点で①②も cloud-init 経由で配置されるため、**Ansible を一度も実行しなくてもサーバーは動く**。Ansible は day-2 更新の手段に限定する。

### なぜこの2点だけ Ansible 側に必要か

| 対象 | 構築後にしか確定しない理由 |
| --- | --- |
| `monitor.py` の `FILESYSTEM_NAME` | `FilesystemUtilization` の `fileSystemName` ディメンションは実測値。`/` ではなく `/dev/sda1` のことがある |
| `monitor.py` の TPS 正規表現 | PaperMC のバージョンで `/tps` の出力形式が変わる |
| `monitor.py` の閾値 | 運用して誤検知の頻度を見てから調整する |
| `.env` の `PLAYIT_SECRET_KEY` | playit.gg の docker 向けセットアップウィザードで先に発行し、`terraform.tfvars` に入れる (空だとコンテナが exit 1 する) |
| `docker-compose.yml` のホワイトリスト・プラグイン | 友人の増減、プラグイン追加のたびに変わる |

### テンプレートの単一の正

同じ `docker-compose.yml` を cloud-init 用 (`templatefile`) と Ansible 用 (Jinja2) に二重管理しない。**Terraform のテンプレートを唯一の正**とし、レンダリング結果を `local_file` で `ansible/files/` に書き出す。Ansible は Jinja2 テンプレートを持たず、その成果物を `copy` するだけの配送役になる。

```text
terraform/templates/docker-compose.yml.tftpl   ← 唯一の正
        │
        ├─ templatefile() → cloud-init に埋め込み (初回構築)
        └─ local_file      → ansible/files/docker-compose.yml (day-2 更新)
```

同様に `monitor/monitor.py` と `monitor/systemd/*` は `monitor/` 配下が唯一の正で、Terraform (`file()` で読む) と Ansible (直接 `copy`) の両方がそこを参照する。

`ansible/files/` は `.gitignore` 済み。RCON パスワードや Webhook URL を含むため。

### インスタンス置換の事故防止

両インスタンスに `lifecycle { ignore_changes = [metadata, source_details[0].source_id] }` を付けている。

| 効果 | 内容 |
| --- | --- |
| `metadata` を無視 | tfvars を変えても VM が作り直されない = ワールドが消えない |
| `source_id` を無視 | Ubuntu イメージが更新されるたびに差分が出るのを抑える |

意図的に作り直す場合は `terraform apply -replace=oci_core_instance.mc_server` を使う。**実行前にバックアップを取ること** ([05. バックアップ](Spec-05-backup))。

## 公開方式の選定

Minecraft サーバーは**プライベート構成**である。NSG に 25565 の ingress を一切作らず、VM は外部からの新規着信を受け付けない。それでもプレイヤーが接続できるのは、どの方式も **VM 側から外部サービスへアウトバウンド接続を張り、その経路を使い回す**ためである。ファイアウォールは自分から出ていった通信の戻りパケットを許可するので、着信の口を開けなくても通信が成立する。

### 3方式の比較

| | playit.gg | Tailscale | ZeroTier |
| --- | --- | --- | --- |
| 友人側の準備 | 不要 (アドレスを渡すだけ) | アプリ導入 + 招待・承認 | アプリ導入 + ネットワークID入力 |
| 友人のアカウント作成 | 不要 | 必要 (Google等でよい) | 不要 |
| 接続先 | `xxx.playit.gg` | `mc-server:25565` | ZeroTier IP:25565 |
| アクセス制御 | 別途ホワイトリスト必須 | ACL で組み込み | 管理者の承認で制御 |
| 遅延 | エッジ経由で +10〜30ms 程度 | 直結できれば低遅延 | 直結できれば低遅延 |
| 管理者の作業 | トンネル設定のみ | 招待送信 | 参加リクエストの承認 |
| 向く場面 | 不特定・流動的なメンバー | 身内の少人数 | アカウント作成をさせたくない場合 |

SSH は**どの方式を選んでも Tailscale 経由**である。playit.gg / ZeroTier は Minecraft の経路のみを担う。

### 選定: `playit` を既定とする

友人側の準備がゼロで済み、試すまでの摩擦が最も小さい。アクセス制御が方式自体に組み込まれていない弱点は、Minecraft のホワイトリストで補う ([03. ネットワーク・セキュリティ](Spec-03-network-security))。

身内の少人数で固定するなら `tailscale` の方が経路が単純で、SSH と依存先を共通化できる。後から切り替えられる ([06. 運用・保守](Spec-06-operations) の変更管理)。

`enable_zerotier` は `exposure_mode` と独立したフラグで、Tailscale と併設して予備経路にできる。

### 方式ごとのコンテナ構成の違い

| | `playit` | `tailscale` / `zerotier` |
| --- | --- | --- |
| Docker ネットワーク | bridge (`mcnet`) | `network_mode: host` |
| 25565 | ホストに出さない。playit が `mc-router:25565` へ転送し、mc-router が `mc:25565` へ中継 | ホストで listen し iptables で制御 |
| 25575 (RCON) | `10.0.1.10:25575` にバインド。NSG が制御 | ホストで listen し iptables で制御 |
| iptables の 25565 ルール | 不要 | `-i tailscale0` / `-i zt+` のみ ACCEPT |
| 追加コンテナ | mc-router + playit-agent | なし |

`playit` 方式で RCON を iptables で守っていないのは、Docker の DNAT が `INPUT` チェーンを通らないため iptables では制御できないからである。代わりに NSG (監視VMのIPのみ許可) とプライベートIPへのバインドで絞る。

### playit トンネルの死活監視

monitor.py は RCON に直結しているため、Minecraft 本体が生きていて経路だけ落ちている状態を検知できない。この穴は mc-server 側の `playit-check.sh` (cron、10分ごと) が埋める。playit と mc-router の**両方**のコンテナを見る。mc-router が落ちるとトンネルが生きていてもプレイヤーは繋がらないが、RCON は `mc` に直接届くため monitor.py は正常と判定してしまう。
