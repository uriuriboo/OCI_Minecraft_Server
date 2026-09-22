# 02b. Tailscale ACL 設定

前提: `02-post-setup.md` の手順2(Tailscale疎通確認)まで完了していること。

## 設定方針

| 対象 | タグ/グループ | アクセス範囲 |
|---|---|---|
| 自分の操作端末 | `tag:mc-admin` | 全ノードへ全ポート |
| mc-server | `tag:mc-server` | (被アクセス側) |
| mc-monitor | `tag:mc-monitor` | (被アクセス側) |
| 友人 | `group:mc-friends` | mc-server の 25565 のみ |

## 手順

### 1. 自分用のタグ付きAuth Key発行

管理画面 → Settings → Keys → Generate auth key

| 設定 | 値 |
|---|---|
| Tags | `tag:mc-admin` |
| Reusable | ON |
| Ephemeral | OFF |

発行したキーで自分の操作端末(PC/スマホ)を tailnet に参加させます。

```bash
# 自分の端末で
tailscale up --authkey=<発行したキー>
```

すでに参加済みの端末なら、タグの再割り当てのみで構いません(手順4参照)。

### 2. mc-server / mc-monitor 用のタグ付きAuth Key発行

同様に、それぞれ別のキーを発行します。

| キー用途 | Tags |
|---|---|
| mc-server用 | `tag:mc-server` |
| mc-monitor用 | `tag:mc-monitor` |

`terraform.tfvars` の `tailscale_authkey` に、共通のReusableキーを使っている場合はここを分割する必要があります。

```hcl
variable "tailscale_authkey_server" {
  type      = string
  sensitive = true
}

variable "tailscale_authkey_monitor" {
  type      = string
  sensitive = true
}
```

cloud-init 側もタグ付きで参加するように変更します。

```yaml
# cloud-init/mc-server.yaml
- tailscale up --authkey=${tailscale_authkey} --ssh --hostname=mc-server --advertise-tags=tag:mc-server
```

```yaml
# cloud-init/mc-monitor.yaml
- tailscale up --authkey=${tailscale_authkey} --ssh --hostname=mc-monitor --advertise-tags=tag:mc-monitor
```

既にタグなしで参加済みの場合は、VMを作り直さずに再実行することもできます。

```bash
ssh ubuntu@mc-server
sudo tailscale up --authkey=<mc-server用キー> --ssh --advertise-tags=tag:mc-server
```

### 3. ACL ポリシーの設定

管理画面 → Access Controls (`login.tailscale.com/admin/acls`) を開き、JSON を以下に置き換えます。

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

`group:mc-friends` は空リストのまま保存して構いません(手順6で追加します)。

保存すると即座に反映されます。

### 4. 既存ノードへのタグ再割り当て(手順1〜2で既に参加済みの場合)

管理画面 → Machines → 対象ノードの「…」メニュー → 「Edit ACL tags」

| ノード | 付けるタグ |
|---|---|
| 自分の端末 | `tag:mc-admin` |
| mc-server | `tag:mc-server` |
| mc-monitor | `tag:mc-monitor` |

### 5. 動作確認

自分の端末から:

```bash
ssh ubuntu@mc-server      # 繋がるはず
ssh ubuntu@mc-monitor     # 繋がるはず
```

タグ付け直後は反映まで数十秒かかることがあります。繋がらない場合は少し待って再試行してください。

### 6. 友人の招待

管理画面 → Settings → Users → Invite external users → 友人にリンクを送付

友人が参加を承諾した後、ACL の `group:mc-friends` に招待時のメールアドレスを追記します。

```json
"groups": {
  "group:mc-friends": [
    "friend1@example.com"
  ]
}
```

保存すると反映されます。

### 7. 友人側での検証

```bash
# 友人の端末から
nc -zv mc-server 25565    # 届くはず
nc -zv mc-server 22       # 届かないはず(SSHはmc-adminのみ)
ping mc-monitor           # 届かないはず(mc-monitorへのアクセス権なし)
```

いずれかが期待と異なる場合、`tagOwners` の割り当てと `acls`/`ssh` ブロックの対象が一致しているか、管理画面の「Access」タブ(対象ノードのアクセス可否を図示してくれる)で確認します。

### 8. Auth Key の期限管理

`02-post-setup.md` の手順3(Key expiry無効化)は、タグ付けが完了した後に実施してください。順序を逆にすると、無効化状態のノードにタグを
