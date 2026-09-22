# 08. 公開方式の選択（playit.gg / Tailscale・ZeroTier）

## 前提

Minecraft サーバーは**プライベート構成**です。OCI の NSG に 25565 の ingress ルールを一切作らず、VM は外部からの新規着信を受け付けません。

それでもプレイヤーが接続できるのは、どちらの方式も **VM 側から外部サービスへアウトバウンド接続を張り、その経路を使い回す** ためです。ファイアウォールは自分から出ていった通信の戻りパケットを許可するので、着信の口を開けなくても通信が成立します。

## 選択肢の比較

| | playit.gg | Tailscale / ZeroTier |
|---|---|---|
| 友人側の準備 | 不要（アドレスを渡すだけ） | アプリ導入 + 招待/承認 |
| 接続先 | `xxx.playit.gg` | `mc-server:25565` |
| アクセス制御 | ホワイトリスト等で別途 | 参加者のみ（制御が組み込み） |
| 遅延 | エッジ経由で +10〜30ms 程度 | 直結できれば低遅延 |
| 依存先 | playit.gg の可用性 | Tailscale / ZeroTier の可用性 |
| 運用の手間 | トンネル設定のみ | 参加者ごとに招待・承認 |
| 向く場面 | 不特定・流動的なメンバー | 身内の少人数 |

SSH は**どちらを選んでも Tailscale 経由**です。playit.gg は Minecraft のトンネルのみを担います。

---

# 方式A: playit.gg

## 通信の流れ

```
[プレイヤー]
   │ 接続: xxx.playit.gg:12345
   ▼
[playit.gg エッジサーバー]
   ▲
   │ 常時確立済みのアウトバウンド接続
   │ (VM → playit.gg 方向に張られている)
   │
[playit エージェント (mc-server 内)]
   │ mc:25565 へ転送
   ▼
[PaperMC コンテナ]
```

## docker-compose.yml

Minecraft 側のポート公開をやめ、playit エージェントを同一 Docker ネットワークに置きます。

```yaml
services:
  mc:
    image: itzg/minecraft-server
    container_name: mc
    tty: true
    stdin_open: true
    restart: unless-stopped
    ports:
      - "10.0.1.10:25575:25575"   # RCON のみ。25565 は公開しない
    environment:
      EULA: "TRUE"
      TYPE: "PAPER"
      VERSION: "LATEST"
      MEMORY: "8G"
      USE_AIKAR_FLAGS: "true"
      TZ: "Asia/Tokyo"
      ENABLE_RCON: "true"
      RCON_PASSWORD: "${RCON_PASSWORD}"
      RCON_PORT: 25575
      MOTD: "OCI Minecraft Server"
      DIFFICULTY: "normal"
      MAX_PLAYERS: 20
      VIEW_DISTANCE: 8
      SIMULATION_DISTANCE: 6
      ENABLE_AUTOPAUSE: "false"
    volumes:
      - ./data:/data
    networks:
      - mcnet

  playit:
    # イメージとタグの正は terraform/templates/docker-compose.yml.tftpl
    image: ghcr.io/playit-cloud/playit-agent:<tag>
    container_name: playit
    restart: unless-stopped
    env_file:
      - .env
    networks:
      - mcnet
    depends_on:
      - mc

networks:
  mcnet:
    driver: bridge
```

`network_mode: "host"` ではなく通常の bridge ネットワークを使います。playit エージェントはコンテナ名 `mc` で Minecraft に到達するため、ホスト側にポートを出す必要がありません。

## cloud-init の差分

```yaml
runcmd:
  - curl -fsSL https://tailscale.com/install.sh | sh
  - tailscale up --authkey=${tailscale_authkey} --ssh --hostname=mc-server --advertise-tags=tag:mc-server
  - usermod -aG docker ubuntu
  # 25565 の iptables 開放は不要
  - iptables -I INPUT -s ${subnet_cidr} -p tcp --dport 25575 -j ACCEPT
  - iptables -A INPUT -p tcp --dport 25575 -j DROP
  - netfilter-persistent save
  - mkdir -p /home/ubuntu/minecraft/backups
  - chown -R ubuntu:ubuntu /home/ubuntu/minecraft
  - cd /home/ubuntu/minecraft && docker compose up -d mc mc-router
```

cloud-init は初回起動時に `mc` と `mc-router` のみ起動します（`playit_secret_key` が空だと `exit 1` を繰り返してクラッシュループするため）。`terraform.tfvars` にキーを設定して `terraform apply` した後、`ansible-playbook site.yml -t app`（または手動で `docker compose up -d`）を実行すると `playit` も起動します。

`--advertise-tags=tag:mc-server` は、この方式でも SSH 制御(Tailscale経由)のために付与します。Minecraft本体のアクセス制御には使いません(playit.gg 側のホワイトリストで別途行います)。Auth Key 発行時にタグ権限を持たせておく必要がある点は方式Bと同じです(`03b-tailscale-acl.md` 参照)。

`.env` は Terraform (`terraform.tfvars` の `playit_secret_key`) から生成される。playit-agent コンテナには `.env` をまるごと渡さず、`docker-compose.yml` の `environment: SECRET_KEY: "$${PLAYIT_SECRET_KEY}"` で必要な1つだけを渡す（RCON パスワードなどを playit コンテナに触れさせないため）。

## セットアップ手順

playit-agent のエントリポイントは `SECRET_KEY` が空だと認証URLを出さずに `exit 1` する。そのため、**先に playit.gg の docker 向けセットアップウィザードでキーを発行してから** VM に渡す。

```bash
# playit.gg ダッシュボード → Add Agent (docker) でシークレットキーを発行
```

発行したキーを `terraform.tfvars` の `playit_secret_key` に設定し、`terraform apply` する（`.env` は自動生成される）。

```bash
ssh ubuntu@mc-server
cd ~/minecraft
docker compose up -d
docker compose logs -f playit
```

## トンネル作成

playit.gg ダッシュボード → Add Tunnel

| 項目 | 値 |
|---|---|
| Type | Minecraft Java |
| Local address | `mc:25565` |

割り当てられた `xxx.playit.gg` がプレイヤー向けアドレスです。

## トンネルの死活監視

`monitor.py` は RCON 直結なので、playit だけ落ちているケースを検知できません。mc-server 側で補います。

```bash
sudo nano /usr/local/bin/playit-check.sh
```

```bash
#!/bin/bash
if [ "$(docker inspect -f '{{.State.Running}}' playit 2>/dev/null)" != "true" ]; then
  curl -H "Content-Type: application/json" \
    -d '{"content":"🚨 playit トンネルが停止しています"}' \
    <DISCORD_WEBHOOK_URL>
fi
```

```bash
sudo chmod 700 /usr/local/bin/playit-check.sh
(crontab -l 2>/dev/null; echo "*/10 * * * * /usr/local/bin/playit-check.sh") | crontab -
```

## アクセス制御

playit.gg のアドレスは知っていれば誰でも接続を試せます。身内だけにするならホワイトリストを併用してください。

```yaml
environment:
  ENFORCE_WHITELIST: "true"
  WHITELIST: "player1,player2"   # 許可するMCID
```

---

# 方式B: Tailscale のみ

## 通信の流れ

```
[VM] ←── WireGuardトンネル ──→ [Tailscale コーディネーション]
                                        │
[友人のPC] ←── WireGuardトンネル ───────┘
```

VM は `100.x.x.x` という tailnet 専用アドレスしか持たず、参加者以外からは到達できません。インターネット上に存在しないアドレスなのでスキャンにも掛かりません。

## docker-compose.yml

`network_mode: "host"` にして、ホストの iptables で制御します。

```yaml
services:
  mc:
    image: itzg/minecraft-server
    container_name: mc
    tty: true
    stdin_open: true
    restart: unless-stopped
    network_mode: "host"
    environment:
      EULA: "TRUE"
      TYPE: "PAPER"
      VERSION: "LATEST"
      MEMORY: "8G"
      USE_AIKAR_FLAGS: "true"
      TZ: "Asia/Tokyo"
      ENABLE_RCON: "true"
      RCON_PASSWORD: "${RCON_PASSWORD}"
      RCON_PORT: 25575
      MOTD: "OCI Minecraft Server"
      DIFFICULTY: "normal"
      MAX_PLAYERS: 20
      VIEW_DISTANCE: 8
      SIMULATION_DISTANCE: 6
      ENABLE_AUTOPAUSE: "false"
    volumes:
      - ./data:/data
```

## cloud-init の差分

```yaml
runcmd:
  - curl -fsSL https://tailscale.com/install.sh | sh
  - tailscale up --authkey=${tailscale_authkey} --ssh --hostname=mc-server --advertise-tags=tag:mc-server
  - usermod -aG docker ubuntu
  # 25565 は tailscale0 経由のみ許可、それ以外は拒否
  - iptables -I INPUT -i tailscale0 -p tcp --dport 25565 -j ACCEPT
  - iptables -A INPUT -p tcp --dport 25565 -j DROP
  - iptables -I INPUT -s ${subnet_cidr} -p tcp --dport 25575 -j ACCEPT
  - iptables -A INPUT -p tcp --dport 25575 -j DROP
  - netfilter-persistent save
  - mkdir -p /home/ubuntu/minecraft/backups
  - chown -R ubuntu:ubuntu /home/ubuntu/minecraft
  - cd /home/ubuntu/minecraft && docker compose up -d
```

`tailscale0` インターフェース経由の 25565 だけを ACCEPT し、他は DROP します。ルールの順序が重要で、ACCEPT が DROP より上位にある必要があります。

`--advertise-tags=tag:mc-server` を付けることで、起動と同時に ACL 上の `tag:mc-server` が付与されます。ただし、この動作には Auth Key 発行時点で対応するタグの権限(`tagOwners`)が有効になっている必要があるため、Auth Key自体をタグ指定で発行しておくのが確実です(詳細は `03b-tailscale-acl.md` を参照)。

mc-monitor 用の cloud-init(`02-terraform.md` に記載)にも同様の追記が必要です。

```yaml
- tailscale up --authkey=${tailscale_authkey} --ssh --hostname=mc-monitor --advertise-tags=tag:mc-monitor
```

## 友人の招待

管理画面 → Settings → Users → Invite external users

友人は自分の Google / Microsoft アカウントなどでログインして参加します。

## ACL 設定

詳細な設定手順(タグ付きAuth Keyの発行、既存ノードへの再割り当て、友人招待後のグループ追記など)は `03b-tailscale-acl.md` を参照してください。以下は完成形のポリシーです。

```json
{
  "groups": {
    "group:mc-friends": []
  },

  "tagOwners": {
    "tag:mc-admin":   ["autogroup:admin"],
    "tag:mc-server":  ["autogroup:admin"],
    "tag:mc-monitor": ["autogroup:admin"],
    "tag:mc-friend":  ["autogroup:admin"]
  },

  "acls": [
    {
      "action": "accept",
      "src":    ["tag:mc-admin"],
      "dst":    ["*:*"]
    },
    {
      "action": "accept",
      "src":    ["group:mc-friends"],
      "dst":    ["tag:mc-server:25565"]
    }
  ],

  "ssh": [
    {
      "action": "accept",
      "src":    ["tag:mc-admin"],
      "dst":    ["tag:mc-server", "tag:mc-monitor"],
      "users":  ["ubuntu", "autogroup:nonroot"]
    }
  ]
}
```

友人は `group:mc-friends` に招待済みメールアドレスを追記することでアクセスできます。管理者(`tag:mc-admin`)は全ノードへ、mc-server/mc-monitor(`tag:mc-server`/`tag:mc-monitor`)は被アクセス側としてタグを持ちます。監視VM(mc-monitor)は友人からは一切見えません。

## 接続方法

```
mc-server:25565
```

MagicDNS が有効ならホスト名で繋がります。無効な場合は `tailscale ip -4` で確認した `100.x.x.x` を使います。

## キー期限の無効化

管理画面 → Machines → 各ノード → Disable key expiry

Auth Key の期限（最長90日）とは別に、各ノードにも再認証期限があります。無人稼働のサーバーでこれが切れると接続できなくなります。

---

# 方式C: ZeroTier

Tailscale とほぼ同じ仕組みですが、招待方法が異なります。

| | Tailscale | ZeroTier |
|---|---|---|
| 参加方法 | 管理者が招待 → 友人がアカウントでログイン | 管理者がネットワークID発行 → 友人がIDを入力 → 管理者が承認 |
| 友人のアカウント | 必要（Google等でOK） | 不要 |
| 管理者の作業 | 招待送信 | 参加リクエストの承認 |

## インストール

```yaml
runcmd:
  - curl -s https://install.zerotier.com | bash
  - zerotier-cli join ${zerotier_network_id}
```

管理画面（my.zerotier.com）で該当ノードを承認すると、`10.147.x.x` のような ZeroTier IP が割り当てられます。

## iptables

```yaml
  - iptables -I INPUT -i zt+ -p tcp --dport 25565 -j ACCEPT
  - iptables -A INPUT -p tcp --dport 25565 -j DROP
```

ZeroTier のインターフェース名は `zt` で始まる可変名なので、`zt+` とワイルドカード指定します。

## 選び方

友人にアカウント作成を強制したくないなら ZeroTier、招待作業を簡単にしたいなら Tailscale です。SSH を Tailscale で運用しているなら、ネットワークを二重に持たない意味で Tailscale に寄せる方が管理は楽になります。

---

# 判断の目安

```
遊ぶ人が流動的・技術に詳しくない
   → playit.gg + ホワイトリスト

身内の少人数で固定
   → Tailscale（SSHと共通化できる）

友人にアカウント作成をさせたくない
   → ZeroTier

とりあえず試したい
   → playit.gg（友人側の準備がゼロ）
```

後から切り替えられます。docker-compose.yml と iptables を書き換えるだけで、ワールドデータには影響しません。