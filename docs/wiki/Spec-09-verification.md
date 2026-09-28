<!-- このページは docs/spec/09-verification.md から生成しています。直接編集しないでください。
     修正は docs/spec/ 側に入れて `python scripts/sync-wiki.py` を実行してください。 -->

# 09. 検証方法

2段構えで検証する。

| 段階 | 何を確かめるか | クラウド |
| --- | --- | --- |
| **静的検証** | コードが構文的に正しく、設定が食い違っていないか | 不要 |
| **受入試験** | 実際に動くか | 必要 |

## 静的検証

クラウドに繋がずに実行できる。コードを変えたら毎回通す。

```bash
# Terraform: 整形・構文・参照の妥当性
cd terraform
tenv tf install                  # .terraform-version の版を使う
terraform fmt -check -recursive
terraform init -backend=false
terraform validate

# リポジトリ内の設定の整合性 (改行コードの検査を含む)
cd ..
uv run scripts/check-consistency.py

# wiki が spec と同期しているか
uv run scripts/sync-wiki.py --check

# Python 構文
uv run python -m py_compile monitor/monitor.py

# requirements.txt が pyproject.toml と一致しているか
uv pip compile pyproject.toml --group monitor -o /tmp/req.txt
diff /tmp/req.txt monitor/requirements.txt

# Ansible 構文 (WSL2 または Linux)
ansible-playbook -i ansible/inventory_sample.yml ansible/site.yml --syntax-check

# シェルスクリプト
bash -n scripts/restore.sh scripts/deploy-monitor.sh
shellcheck scripts/*.sh          # 任意

# JSON
python -m json.tool dashboards/oci-dashboard.json > /dev/null
```

VS Code では `Ctrl+Shift+P` → Tasks: Run Task → `check: すべて` でまとめて実行できる。

> **検証コマンド自体が動いていることを確かめる**
>
> PowerShell から WSL 経由で `bash -n` を呼ぶと、クォート処理の問題で**コマンドが実行されないまま成功したように見える**ことがある。実際にこれで CRLF の不具合を一度見逃した ([A1. 手順書との差分](Spec-A1-doc-reconciliation) の 3-6)。
>
> 検証は入り組んだシェルのワンライナーにせず、スクリプトファイルにして実行すること。意図的に壊したファイルで失敗することを一度確認しておくとよい。

### `check-consistency.py` の検査内容

| # | 検査 | 何を防ぐか |
| --- | --- | --- |
| 1 | monitor.py が必須とする環境変数が、テンプレートとサンプルの両方にあるか | VM 上で `KeyError` になる事故 |
| 2 | テンプレート / サンプルに monitor.py が読まない変数がないか | 綴り違いと不要な設定の放置 |
| 3 | `docker-compose` が参照する変数が `.env` テンプレートにあるか | compose の変数展開が空になる事故 |
| 4 | `variables.tf` の全変数が `terraform.tfvars_sample` に載っているか | 必須変数の記載漏れ |
| 5 | `.gitignore` が秘密ファイルを捕捉しているか | 秘密のコミット |
| 6 | `docs/spec/` の各章に対応する `docs/wiki/` のページがあるか | wiki の同期漏れ |
| 7 | VM へ配るファイルが CRLF になっていないか | `.env` の値に `\r` が付いて RCON 認証が失敗する等 |

### テンプレートのレンダリング確認

`exposure_mode` の3値すべてと、リストが空の場合・`mc_router_auto_scale = true` の場合で、cloud-init と docker-compose が矛盾しないことを確認する。以下は使い捨ての検証用構成で、`local` プロバイダだけで動く。

```bash
# terraform console でも確認できる
cd terraform
terraform console
> templatefile("templates/docker-compose.yml.tftpl", { exposure_mode = "playit", ... })
```

確認すべき点。

| 項目 | 期待 |
| --- | --- |
| cloud-init が YAML として妥当か | `cloud-init schema --config-file <rendered>` が通る |
| `write_files` の各ファイルが完全に埋まっているか | `monitor.py` が途中で切れていない |
| compose が妥当か | `docker compose -f <rendered> config` が通る |
| `playit` 方式 | `ports: 10.0.1.10:25575:25575` があり、25565 の iptables ルールがない |
| `tailscale` 方式 | `network_mode: host` で `-i tailscale0` の ACCEPT が DROP より前 |
| `zerotier` 方式 | `-i zt+` の ACCEPT が DROP より前 |
| mc-router の有無 | `playit` にだけ出る。`tailscale` / `zerotier` には出ない |
| mc-router (既定) | `DEFAULT: "mc:25565"` があり、**`docker.sock` を渡していない** |
| mc-router (`auto_scale=true`) | `IN_DOCKER` / `AUTO_SCALE_UP` / `user: "0:0"` / `mc` 側の `mc-router.*` ラベルが揃う |
| cloud-init の初回起動 | `playit` で `docker compose up -d mc mc-router` (playit はキー未設定時のクラッシュループを避けて除外) |
| compose の `$${RCON_PASSWORD}` | `${RCON_PASSWORD}` としてそのまま残る (Terraform に食われない) |
| `backup.sh` の `$((...))` | シェルの算術展開として残る (`$$((...))` になっていない) |
| `mc_whitelist` が空 | `ENFORCE_WHITELIST` の行が出力されない |
| 改行コード | レンダリング結果に CRLF が含まれない |

レンダリング結果に対して実際に `bash -n` を通すこと。目視では CRLF や `$$` の混入に気づけない。

```bash
bash -n rendered-backup.sh rendered-playit-check.sh
```

## 受入試験

構築順に並べている。**V-03 は V-04 の前に必ず合格させること。** 逆にすると SSH の口がゼロになる。

### フェーズ1: 事前準備

| # | 項目 | 手順 | 期待 |
| --- | --- | --- | --- |
| V-01 | OCI CLI の疎通 | `oci iam region list` | リージョン一覧が返る |
| V-02 | R2 の疎通 | (構築後に mc-server で) `rclone lsd r2:` | バケット一覧が返る |

### フェーズ2: 構築と管理アクセス

| # | 項目 | 手順 | 期待 |
| --- | --- | --- | --- |
| V-03 | **Tailscale 疎通 (最重要)** | `ssh ubuntu@mc-server` / `ssh ubuntu@mc-monitor` | どちらもログインできる |
| V-04 | SSH 穴を閉じる | `enable_home_ssh=false` → `terraform apply` → V-03 を再確認 | 閉じた後も Tailscale で入れる |
| V-05 | パスワード認証の無効化 | `sudo sshd -T \| grep -i passwordauthentication` | `passwordauthentication no` |
| V-06 | cloud-init の完了 | `cloud-init status --wait` | `status: done` |
| V-07 | Tailscale キー期限 | 管理画面 → Machines | 両ノードで Key expiry が無効 |

V-07 はタグ付けが完了した**後**に実施する。

### フェーズ3: Minecraft

| # | 項目 | 手順 | 期待 |
| --- | --- | --- | --- |
| V-08 | サーバー起動 | `cd ~/minecraft && docker compose logs -f` | `Done (xx.xxx s)! For help, type "help"` |
| V-09 | プレイヤー接続 | クライアントから接続 | ワールドに入れる |
| V-09a | コンテナ構成 (playit) | `docker compose ps` | `mc` / `mc-router` / `playit` の3つが Up |
| V-09b | mc-router の中継 (playit) | V-09 の接続中に `docker compose logs mc-router` | `mc:25565` への routing が記録される |
| V-10 | ホワイトリスト | `docker compose exec mc rcon-cli whitelist list` | 登録した MCID が並ぶ |
| V-11 | online-mode | `docker compose exec mc rcon-cli` で確認 | `true` |

V-09a の `playit` は、キーを設定して Ansible `-t app` を実行した後に確認する。cloud-init 直後は `mc` と `mc-router` の2つだけである (キーが空だと playit がクラッシュループするため起動していない)。

`exposure_mode` 別の V-09 の接続先。

| 方式 | 接続先 | 追加確認 |
| --- | --- | --- |
| `playit` | playit.gg ダッシュボードの `xxx.playit.gg` | Add Tunnel で Local address を **`mc-router:25565`** に設定済みか (`mc:25565` ではない) |
| `tailscale` | `mc-server:25565` | MagicDNS 無効なら `tailscale ip -4` の `100.x.x.x` |
| `zerotier` | ZeroTier IP:25565 | my.zerotier.com でノードを承認済みか |

### フェーズ4: 監視

| # | 項目 | 手順 | 期待 |
| --- | --- | --- | --- |
| V-12 | 標準メトリクス | コンソール → 監視 → メトリクス・エクスプローラ、ネームスペース `oci_computeagent`、メトリック `MemoryUtilization` | 値が出る (反映に5〜10分) |
| V-13 | **`fileSystemName` の実測値** | 同画面で `FilesystemUtilization` のディメンションを確認 | 値を控える。`/` でないことがある |
| V-14 | `filesystem_name` の反映 | 控えた値を `terraform.tfvars` に設定 → `terraform apply` → Ansible `-t monitor` | ディスク使用率が取得できる |
| V-15 | RCON 疎通 | mc-monitor で `nc -zv 10.0.1.10 25575` | `succeeded` |
| V-16 | **TPS 出力形式** | 下記のスクリプト | `tps` と `list` の生出力が期待形式か |
| V-17 | 監視の単発実行 | `sudo systemctl start mc-monitor.service` → `journalctl -u mc-monitor.service -n 30` | エラーなく完了 |
| V-18 | Discord 着弾 | `monitor_thresholds.cpu` を一時的に `0.0` にして適用 → 単発実行 | Discord にアラートが届く。確認後に戻す |
| V-19 | カスタムメトリクス | メトリクス・エクスプローラ、ネームスペース `custom_minecraft` | `TPS` / `PlayerCount` / `ServerOnline` が出る |
| V-20 | タイマー稼働 | `systemctl list-timers mc-monitor.timer` | 次回実行時刻が表示される |
| V-21 | ダッシュボード | `python scripts/print-dashboard.py` の出力でウィジェットを作成 | 全ウィジェットに値が出る |

V-16 のスクリプト。

```bash
ssh ubuntu@mc-monitor
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

`tps` の出力は `TPS from last 1m, 5m, 15m: 20.0, 20.0, 20.0` の形を想定している。数値を全て拾って後ろから3番目 (= 直近1分) を使う。形式が違う場合は `monitor/monitor.py` の正規表現を調整する。

V-19 で 401 が出る場合は `iam.tf` の `use metrics` 権限が適用されているかを確認する。

### フェーズ5: バックアップ

| # | 項目 | 手順 | 期待 |
| --- | --- | --- | --- |
| V-22 | バックアップ実行 | `~/minecraft/backup.sh` | 全段階が成功し `backup done` が出る |
| V-23 | R2 への転送 | `rclone ls r2:minecraft-backup` | `.tgz` が存在する |
| V-24 | OCI への転送 | コンソール → Object Storage → バケット | 同じ `.tgz` が存在する |
| V-25 | 世代整理 | 8回以上実行後に `ls ~/minecraft/backups` | `.tgz` が `backup_keep_generations` 個に収まる |
| V-26 | **復元 (最重要)** | `~/restore.sh` を通す | ワールドが戻り、サーバーが起動する |

**V-26 は構築直後に一度実施する。** バックアップは復元できて初めて機能する。

### フェーズ6: セキュリティ

| # | 項目 | 手順 | 期待 |
| --- | --- | --- | --- |
| V-27 | 受信ポートが 0 | 外部から `nmap -Pn <public_ip>` | 25565 / 25575 / 22 すべて閉じている |
| V-28 | 友人のアクセス範囲 (tailscale/zerotier) | 友人の端末から下記 | 25565 のみ到達 |
| V-29 | RCON が閉域 | 外部から `nc -zv <public_ip> 25575` | 到達しない |
| V-30 | iptables の順序 (tailscale/zerotier) | `sudo iptables -L INPUT -n --line-numbers` | ACCEPT が DROP より上の行番号 |

V-28 の確認。

```bash
# 友人の端末から
nc -zv mc-server 25565    # 届くはず
nc -zv mc-server 22       # 届かないはず (SSH は tag:mc-admin のみ)
ping mc-monitor           # 届かないはず (アクセス権なし)
```

期待と異なる場合は、`tagOwners` の割り当てと `acls` / `ssh` ブロックの対象が一致しているかを、管理画面の Access タブ (ノードのアクセス可否を図示してくれる) で確認する。

### フェーズ7: プラグインと権限

| # | 項目 | 手順 | 期待 |
| --- | --- | --- | --- |
| V-31 | CoreProtect | `docker compose exec mc rcon-cli co inspect` | 検査モードに入る |
| V-32 | LuckPerms | `docker compose exec mc rcon-cli lp info` | 情報が返る |
| V-33 | OP | `docker compose exec mc rcon-cli op <MCID>` | 付与できる |

### フェーズ8: 変更の反映経路

| # | 項目 | 手順 | 期待 |
| --- | --- | --- | --- |
| V-34 | Ansible の app タグ | `mc_motd` を変更 → `terraform apply` → `ansible-playbook site.yml -t app` | MOTD が変わり、**VM は再作成されない** |
| V-35 | Ansible の monitor タグ | 閾値を変更 → 同様に `-t monitor` | 閾値が反映される |
| V-36 | VM が保護されているか | `terraform plan` の出力を確認 | インスタンスの `replace` が計画に出ない |
| V-37 | `exposure_mode` の切り替え | [06. 運用・保守](Spec-06-operations) の手順 | ワールドを維持したまま切り替わる |

V-36 は最も重要な回帰試験である。`terraform plan` に `must be replaced` が出た場合、**apply する前に止まること**。

## 検証状況

| フェーズ | 実施日 | 結果 | 実施者 |
| --- | --- | --- | --- |
| 静的検証 | | | |
| 1. 事前準備 | | | |
| 2. 構築と管理アクセス | | | |
| 3. Minecraft | | | |
| 4. 監視 | | | |
| 5. バックアップ | | | |
| 6. セキュリティ | | | |
| 7. プラグインと権限 | | | |
| 8. 変更の反映経路 | | | |
