<!-- このページは docs/spec/03-network-security.md から生成しています。直接編集しないでください。
     修正は docs/spec/ 側に入れて `python scripts/sync-wiki.py` を実行してください。 -->

# 03. ネットワーク設計とセキュリティ設計

## 多層防御の全体像

到達を4つの層で絞る。どれか1つが破れても他が残るように、層ごとに違う属性で判定する。

| 層 | 何で判定するか | 実装 |
| --- | --- | --- |
| 1. 経路の不在 | インターネットから到達可能なポートがない | NSG に ingress を作らない |
| 2. オーバーレイの参加 | tailnet / ZeroTier ネットワークのメンバーか | Tailscale ACL / ZeroTier の承認 |
| 3. インターフェース | どの NIC から来たパケットか | iptables (`-i tailscale0` / `-i zt+`) |
| 4. アカウント | どの Minecraft アカウントか | `ENFORCE_WHITELIST` + `ONLINE_MODE` |

層2・3が「どのIPから来たか」しか見ないのに対し、層4は「誰としてログインしようとしたか」を見る。**この2つは別物なので併用が必要**である。友人の端末が tailnet に入っていても、そこから無関係な第三者の MCID でログインを試すことは技術的に可能だからである。

## OCI ネットワーク

| リソース | 設定 | 備考 |
| --- | --- | --- |
| VCN | `10.0.0.0/16`、dns_label `mcvcn` | |
| Public Subnet | `10.0.1.0/24`、dns_label `public` | パブリックIPは付与するが ingress を開けない |
| Internet Gateway | 有効 | アウトバウンド用 |
| Route Table | `0.0.0.0/0` → IGW | |
| Security List | **egress のみ** 全許可 | ingress 制御は NSG に一本化する |
| mc-server | `10.0.1.10`、hostname `mcserver` | |
| mc-monitor | `10.0.1.20`、hostname `mcmonitor` | |

パブリックIPを付けるのはアウトバウンド接続 (Tailscale / playit / apt / R2) のためで、着信のためではない。

### ingress 制御を NSG に一本化する理由

セキュリティリストと NSG の両方で許可・拒否を書くと、「どちらで塞がれているのか」の切り分けに時間がかかる。ingress は NSG だけに書き、セキュリティリストは egress の受け皿に留める。

### NSG ルール

#### nsg-minecraft

| 方向 | プロトコル | ポート | 送信元 | 条件 | 目的 |
| --- | --- | --- | --- | --- | --- |
| INGRESS | TCP | 25575 | `10.0.1.20/32` | 常時 | RCON。監視VMのみ |
| INGRESS | TCP | 22 | `home_ip_cidr` | `enable_home_ssh=true` | 初回構築のフォールバック |
| EGRESS | all | all | `0.0.0.0/0` | 常時 | トンネル・更新・バックアップ |

#### nsg-monitor

| 方向 | プロトコル | ポート | 送信元 | 条件 | 目的 |
| --- | --- | --- | --- | --- | --- |
| INGRESS | TCP | 22 | `home_ip_cidr` | `enable_home_ssh=true` | 初回構築のフォールバック |
| EGRESS | all | all | `0.0.0.0/0` | 常時 | RCON・Monitoring API・Discord |

**25565 の ingress ルールはどの `exposure_mode` でも存在しない。**

### 初回構築時の SSH 穴

`enable_home_ssh = true` のときだけ自宅IPからの 22 番が開く。Tailscale の疎通を確認したら `false` にして再 apply し、外部公開ポートを 0 にする。

この順序は逆にできない。Tailscale が繋がらない状態で穴を閉じると、**どこからも入れなくなる**。そのため受入試験 (V-03) を合格させてから V-04 に進む。

`enable_home_ssh = true` かつ `home_ip_cidr` が空だと NSG ルールの `source` が不正になり apply が中途で失敗するため、Terraform の変数 validation で事前に弾いている。

## VM 内のファイアウォール (iptables)

`exposure_mode` により内容が変わる。

### `tailscale` / `zerotier`

```text
-I INPUT -i tailscale0 -p tcp --dport 25565 -j ACCEPT   # または -i zt+
-A INPUT               -p tcp --dport 25565 -j DROP
-I INPUT -s 10.0.1.0/24 -p tcp --dport 25575 -j ACCEPT
-A INPUT                -p tcp --dport 25575 -j DROP
```

`-I` (先頭挿入) と `-A` (末尾追加) を使い分けている。**ACCEPT が DROP より上位にある必要がある**ため。ルールの順序が逆になると全拒否になる。

ZeroTier のインターフェース名は `zt` で始まる可変名なので `zt+` とワイルドカード指定する。

`netfilter-persistent save` で再起動後も残す。

### `playit`

25565 をホストに出していないため、塞ぐ対象がない。playit と mc-router はどちらも bridge (`mcnet`) の中だけで通信し、ホストのポートを一切公開しない。

RCON は Docker の `ports` で `10.0.1.10:25575` にバインドしており、**Docker の DNAT は `INPUT` チェーンを通らない**ため iptables では守れない。監視VMからのみという制御は NSG が担う。

この制約があるため、mc-router を `tailscale` / `zerotier` 方式には入れていない。mc-router を挟むと `mc` を bridge に移すことになり、25565 が Docker の公開ポートになって**層3 の iptables が効かなくなる**ためである ([02. アーキテクチャ](Spec-02-architecture))。

### 接続レート制限 (playit のみ)

playit.gg のアドレスは知っていれば誰でも接続を試せる。mc-router の `CONNECTION_RATE_LIMIT` (`mc_router_rate_limit`、既定 5/秒) が、接続の連打を PaperMC 本体に素通りさせない。

これは多層防御の層1〜4とは別物で、**到達の可否ではなく到達の速度を絞るもの**である。層を増やすものではないので、ホワイトリスト (層4) を省略してよい理由にはならない。小さくしすぎると正当な再接続まで弾かれ、原因の分かりにくい接続不良になる。

## Tailscale

### ACL 設計

| 対象 | タグ / グループ | アクセス範囲 |
| --- | --- | --- |
| 自分の操作端末 | `tag:mc-admin` | 全ノードへ全ポート + SSH |
| mc-server | `tag:mc-server` | (被アクセス側) |
| mc-monitor | `tag:mc-monitor` | (被アクセス側) |
| 友人 | `group:mc-friends` | mc-server の 25565 のみ |

ポリシーの実体は [tailscale/acl.hujson](../blob/main/tailscale/acl.hujson)。管理画面 → Access Controls に貼って保存する。

監視VM (mc-monitor) は `group:mc-friends` からは一切見えない。

### Auth Key はタグ付きで発行する

`terraform.tfvars` の `tailscale_authkey_server` / `tailscale_authkey_monitor` は、それぞれ `tag:mc-server` / `tag:mc-monitor` のタグ権限を付けて発行する。

cloud-init は `tailscale up --advertise-tags=tag:mc-server` で参加するが、**この動作には Auth Key 発行時点で対応するタグ権限が有効になっている必要がある**。タグなしのキーで参加すると ACL の `ssh` ブロックが一致せず、SSH できなくなる。

キーを2本に分けているのは、1本を共用するとタグを出し分けられないためである。

### ノードのキー期限を無効化する

Auth Key の期限 (最長90日) とは別に、各ノードにも再認証期限がある。サーバーは無人稼働が前提なので、これが切れると **SSH の口がゼロになる**。

管理画面 → Machines → 各ノード → Disable key expiry を必ず実施する。**タグ付けが完了した後に**実施すること。順序を逆にすると、無効化状態のノードにタグを割り当て直す手間が生じる。

## SSH

| 項目 | 設定 | 実装 |
| --- | --- | --- |
| パスワード認証 | 無効 | `/etc/ssh/sshd_config.d/99-disable-password.conf` |
| root ログイン | 無効 | 同上 |
| チャレンジレスポンス | 無効 | 同上 |
| 主経路 | Tailscale SSH | ACL の `ssh` ブロックで認可 |
| 副経路 | 公開鍵 + 自宅IP | `enable_home_ssh=true` の間のみ |
| 最終手段 | OCI シリアルコンソール | ネットワーク不要 |

パスワード認証を無効化しているため、鍵を持たない総当たりは成立しない。設定が効いていることは `sudo sshd -T | grep -i passwordauthentication` で確認する (V-05)。

### 最終手段: シリアルコンソール

Tailscale も SSH も使えなくなった場合、OCI コンソール → インスタンス詳細 → リソース → コンソール接続 から OS に直接ログインできる。**この手段が残っているため、外部ポートを全て閉じても完全に詰むことはない。**

## Minecraft レベルのセキュリティ

### ホワイトリスト (必須)

Tailscale ACL でネットワーク到達を絞っていても併用する。理由は前述のとおり、ACL が MCID を見ていないためである。

```yaml
ENFORCE_WHITELIST: "true"
WHITELIST: "friend1_mcid,friend2_mcid"
```

`mc_whitelist` が空リストのときはホワイトリスト自体を無効にする。**`exposure_mode = playit` では実質必須**で、playit.gg のアドレスは知っていれば誰でも接続を試せるためここが唯一のアカウント制御になる。

運用中の追加・削除は RCON 経由でもできるが、`docker-compose.yml` の再生成で上書きされるため、恒久的な変更は `mc_whitelist` に入れる。

```bash
docker compose exec mc rcon-cli whitelist add <MCID>
docker compose exec mc rcon-cli whitelist list
```

### online-mode

```yaml
ONLINE_MODE: "true"
```

`false` だと Mojang 認証をスキップし、どんな MCID 名でも接続できてしまう。なりすましと荒らしの温床になるため明示的に `true` を置いている。デフォルトも `true` だが、明示しておくことで意図しない変更に気づける。

### RCON

| 項目 | 設定 |
| --- | --- |
| ポート | 25575 |
| パスワード | `openssl rand -base64 24` |
| 到達範囲 | VCN 内 (`10.0.1.20` からのみ) |
| インターネット露出 | なし |

RCON は認証が平文のプロトコルなので、Tailscale を経由させず VCN 内で閉じる。閉域なら平文でも問題にならず、監視の経路が Tailscale の可用性に依存しなくなる。

### 破壊対策

| プラグイン | ID | 役割 |
| --- | --- | --- |
| CoreProtect | 8631 | ブロック変更のログとロールバック |
| LuckPerms | 28140 | 段階的な権限管理 |

`mc_plugins` で管理する。CoreProtect は友人内の誤操作 (TNT 爆破、うっかり削除) を巻き戻すためのもので、悪意ある攻撃より事故を想定している。

```bash
docker compose exec mc rcon-cli co inspect
docker compose exec mc rcon-cli co rollback t:1h r:20 u:<プレイヤー名>
```

### 権限設計

人数が少なく信頼できる友人だけなら OP で足りる。OP は「全権限を持つか持たないか」の二値に近く、細かい分けが苦手なので、必要になった時点で LuckPerms を使う。

| グループ | できること |
| --- | --- |
| `default` | 通常プレイのみ |
| `builder` | クリエイティブ関連コマンドの一部 |
| `moderator` | kick / ban、CoreProtect のロールバック |
| `admin` | 全権限 (OP と同等) |

LuckPerms の設定は `./data/plugins/LuckPerms/` に保存され、`data` ディレクトリ全体がバックアップ対象なので追加設定は不要である。

## 秘密情報の取り扱い

| 秘密 | 保管場所 | VM 上の状態 |
| --- | --- | --- |
| OCI APIキー | 管理端末の `~/.oci/` のみ | 置かない |
| OCI へのバックアップ権限 | IAM のインスタンスプリンシパル | 鍵を置かない |
| RCON パスワード | `terraform.tfvars` | `.env` (0600) |
| Discord Webhook | `terraform.tfvars` | `.env` (0600)、`playit-check.sh` (0700) |
| R2 のキー | `terraform.tfvars` | `rclone.conf` (0600) |
| playit シークレット | `terraform.tfvars` | `.env` (0600) |
| Tailscale Auth Key | `terraform.tfvars` | 参加後は不要 (cloud-init のログには残る) |

OCI Object Storage へのバックアップをインスタンスプリンシパルで認証しているのは、**VM が侵害されても他のリソースに広がらないようにする**ためである。権限はバケット1つに限定している。

```text
Allow dynamic-group dg-mc-server-instances to manage objects
  in compartment id <ocid> where target.bucket.name = 'minecraft-backup'
```

リポジトリには `.gitignore` と `*_sample` で投入口を分離している。保護されているかは `scripts/check-consistency.py` が検査する。

### 残っているリスク

| リスク | 現状 | 対処の選択肢 |
| --- | --- | --- |
| `terraform.tfvars` が平文で管理端末にある | 受容 | OCI Vault + Resource Manager へ移行 |
| `terraform.tfstate` に秘密が平文で含まれる | 受容 (ローカルのみ) | リモートバックエンドの暗号化 |
| Tailscale Auth Key が cloud-init ログに残る | 受容 (参加後は無価値) | 使い捨てキーにする |
| Discord Webhook URL を知られると誰でも投稿できる | 受容 (通知先のみ) | 漏洩時は再発行 |
