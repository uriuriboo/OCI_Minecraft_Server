# 01. 事前準備（手動）

Terraform を実行する前に揃えるものです。

## 1. OCI CLI 設定

```bash
bash -c "$(curl -L https://raw.githubusercontent.com/oracle/oci-cli/master/scripts/install/install.sh)"
oci setup config
```

対話で聞かれる項目:

| 項目 | 取得場所 |
|---|---|
| ユーザーOCID | コンソール → プロフィール → ユーザー設定 |
| テナンシーOCID | プロフィール → テナンシー |
| リージョン | `ap-tokyo-1` |

APIキーは自動生成されるので、公開鍵をコンソールに登録します。

```bash
cat ~/.oci/oci_api_key_public.pem
```

コンソール → プロフィール → ユーザー設定 → APIキー → 「公開キーの追加」

```bash
# 疎通確認
oci iam region list
```

## 2. コンパートメントOCID取得

```bash
oci iam compartment list --all --query "data[].{name:name,id:id}" --output table
```

ルートコンパートメントを使う場合はテナンシーOCIDをそのまま使います。

## 3. SSH鍵生成

Tailscale SSH を使いますが、初回構築時のフォールバックとして必要です。

```bash
ssh-keygen -t ed25519 -f ~/.ssh/oci_mc -C "oci-minecraft"
cat ~/.ssh/oci_mc.pub
```

## 4. 自宅グローバルIP確認

初回構築時のみ使用し、Tailscale 疎通確認後に閉じます。

```bash
curl -s https://ifconfig.me
```

## 5. Tailscale Auth Key 発行

`terraform.tfvars` の `tailscale_authkey_server` / `tailscale_authkey_monitor` は最初の `terraform apply` からタグ付きキーを要求する。タグ付きキーを発行するには、先に ACL の `tagOwners` にタグを登録しておく必要がある（[03b-tailscale-acl.md](03b-tailscale-acl.md) 手順3の JSON を参考に、最低限 `tagOwners` だけ先に保存しておく）。

管理画面 → Settings → Keys → Generate auth key で、mc-server用・mc-monitor用の**2本**を発行する。

| 設定 | 値 |
|---|---|
| Tags | mc-server用: `tag:mc-server` / mc-monitor用: `tag:mc-monitor` |
| Reusable | OFF（VMごとに1回しか使わない） |
| Ephemeral | OFF（再起動で消えると困る） |
| Expiration | 90日 |

## 6. RCONパスワード生成

```bash
openssl rand -base64 24
```

## 7. Discord Webhook 作成

対象チャンネル → 編集 → 連携サービス → ウェブフック → 新しいウェブフック → URLをコピー

## 8. Cloudflare R2 準備

R2 → バケット作成（例: `minecraft-backup`）

R2 → 「R2 APIトークンの管理」 → トークン作成

- 権限: **オブジェクトの読み取りと書き込み**
- 対象: 作成したバケットのみに限定

控えるもの（再表示されません）:

- Access Key ID
- Secret Access Key
- エンドポイント `https://<account-id>.r2.cloudflarestorage.com`

## チェックリスト

```
[ ] OCI CLI 設定・APIキー登録
[ ] コンパートメントOCID取得
[ ] SSH鍵生成
[ ] 自宅グローバルIP確認
[ ] Tailscale Auth Key 発行
[ ] RCONパスワード生成
[ ] Discord Webhook 作成
[ ] R2バケット・APIトークン作成
```