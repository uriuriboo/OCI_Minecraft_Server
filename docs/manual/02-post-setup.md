# 02. 構築後の手動作業

## 1. cloud-init 完了待ち

```bash
ssh -i ~/.ssh/oci_mc ubuntu@$(terraform output -raw minecraft_public_ip)
cloud-init status --wait
```

## 2. Tailscale 疎通確認

管理画面に `mc-server` と `mc-monitor` が表示されているか確認します。

```bash
ssh ubuntu@mc-server
ssh ubuntu@mc-monitor
```

**繋がることを確認してから次へ進んでください。** ここで失敗したまま SSH 穴を閉じると、どこからも入れなくなります。

## 2b. SSHパスワード認証の無効化確認

```bash
ssh ubuntu@mc-server
sudo sshd -T | grep -i passwordauthentication
# passwordauthentication no と出ること
```

mc-monitor でも同様に確認します。

## 3. Tailscale キー期限の無効化

管理画面 → Machines → 各ノード → Disable key expiry

Auth Key の期限（最長90日）とは別に、各ノードにも再認証期限があります。サーバーは無人稼働が前提なので、これが切れると SSH の口がゼロになります。

## 4. SSH 穴を閉じる

```bash
# terraform.tfvars
enable_home_ssh = false
```

```bash
terraform apply
```

これで外部公開ポートがゼロになります。

## 5. Minecraft 起動確認

```bash
ssh ubuntu@mc-server
cd ~/minecraft
docker compose logs -f
```

`Done (xx.xxx s)! For help, type "help"` で起動完了です。

## 6. 接続テスト

```bash
tailscale ip -4
```

Minecraft クライアントから接続します。

```text
mc-server:25565
```

MagicDNS が有効ならホスト名で繋がります。

## 7. 友人を招待する場合

管理画面 → Settings → Users → Invite external users

ACL でアクセス範囲を絞ります。タグ名・グループ名を含む ACL の設定手順は [02b-tailscale-acl.md](02b-tailscale-acl.md) が正（`tag:mc-server` / `group:mc-friends` を使う）。

友人は Minecraft ポートのみ、管理者は全ポートにアクセスできます。監視VMは友人から見えません。

## 8. メトリクス確認（重要）

反映に5〜10分かかります。

コンソール → 監視 → メトリクス・エクスプローラ

| 項目 | 値 |
|---|---|
| ネームスペース | `oci_computeagent` |
| メトリック名 | `MemoryUtilization` |

値が出ることを確認し、**`FilesystemUtilization` の `fileSystemName` ディメンションの実際の値を控えてください。** `/` ではなく `/dev/sda1` のようなデバイス名のことがあります。この値は `monitor.py` に反映します。

## 9. RCON 疎通確認

```bash
ssh ubuntu@mc-monitor
nc -zv 10.0.1.10 25575
```

## 10. TPS 出力フォーマット確認

```bash
source ~/venv/bin/activate
python3 -c "
from mcrcon import MCRcon
import os
from dotenv import load_dotenv
load_dotenv()
with MCRcon(os.environ['RCON_HOST'], os.environ['RCON_PASSWORD'], port=25575) as m:
    print(repr(m.command('tps')))
    print(repr(m.command('list')))
"
```

PaperMC のバージョンで出力が変わるため、`monitor.py` の正規表現が合っているか確認します。

## チェックリスト

```text
[ ] cloud-init 完了確認
[ ] Tailscale 疎通確認（重要）
[ ] Tailscale キー期限を無効化
[ ] enable_home_ssh=false で再 apply
[ ] Minecraft 起動確認
[ ] Tailscale 経由で接続テスト
[ ] 友人の招待・ACL設定（必要なら）
[ ] メトリクス確認・fileSystemName 控え
[ ] RCON 疎通確認
[ ] TPS 出力フォーマット確認
```
