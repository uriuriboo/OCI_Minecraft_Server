# 08. 荒らし対策とユーザー権限管理

## 前提

Tailscale ACL(`02b-tailscale-acl.md`)によって、`group:mc-friends` に入っていない人はそもそも 25565 に到達できません。ここでの対策は、**その一線を越えた後**、つまり接続した友人同士の間でのトラブル(誤操作、意図的な破壊、権限の逸脱)を防ぐためのものです。

---

## 荒らし対策

### 1. ホワイトリスト(必須)

Tailscale ACL でネットワーク到達を絞っていても、Minecraft自体のホワイトリストは併用してください。理由は、Tailscale ACLが「どのIPから来たか」しか見ておらず、「どのMinecraftアカウントでログインしようとしたか」は見ていないためです。友人のTailscale経由でも、無関係な第三者のMCIDでログインを試すことは技術的に可能です。

```yaml
# docker-compose.yml
environment:
  ENFORCE_WHITELIST: "true"
  WHITELIST: "friend1_mcid,friend2_mcid"
```

追加・削除はRCON経由でも可能です。

```bash
docker compose exec mc rcon-cli whitelist add <MCID>
docker compose exec mc rcon-cli whitelist remove <MCID>
docker compose exec mc rcon-cli whitelist list
```

### 2. online-mode の確認

デフォルトで `true` になっているはずですが、明示しておくと安心です。

```yaml
environment:
  ONLINE_MODE: "true"
```

これが `false` だと、Mojang認証をスキップしてどんなMCID名でも接続できてしまい、なりすまし・荒らしの温床になります。オフライン認証が必要な特殊事情がない限り `true` のままにしてください。

### 3. 破壊対策プラグイン

友人内のトラブル(誤操作によるTNT爆破、うっかり削除)を想定し、行動を記録・巻き戻せるプラグインを入れておくと安心です。

**CoreProtect**(ブロック変更のログ・ロールバック)

```yaml
environment:
  SPIGET_RESOURCES: "8631"   # CoreProtectのSpigotMC ID
```

```bash
# 誰が何を壊したか調べる
docker compose exec mc rcon-cli co inspect

# 直近1時間分を指定範囲でロールバック
docker compose exec mc rcon-cli co rollback t:1h r:20 u:<プレイヤー名>
```

### 4. ゲームルールでの制限

TNT・火・液体流出などを制限したい場合、`server.properties` やゲームルールで調整できます。

```bash
docker compose exec mc rcon-cli gamerule tntExplodes false
docker compose exec mc rcon-cli gamerule doFireTick false
```

身内サーバーでどこまで縛るかは、遊び方(サバイバル本気勢か、まったり建築か)次第です。最初は緩めにして、問題が起きてから絞る方が現実的です。

### 5. 死活監視との連携(既存機能の活用)

`monitor.py` は既にプレイヤー数を取得しています。急激な人数変化(知らないアカウントが大量ログインした等)があれば異常のサインになるため、閾値監視に「短時間でのプレイヤー数急増」を足すことも検討できます。ただしこれは通常の遊び方でも起こりうる(友人が一斉にログインする)ため、誤検知が多くなりがちです。今の構成では優先度は低く、ホワイトリストで一次防御する方が確実です。

---

## ユーザーへの権限付与管理

### 1. 方針

友人内でも役割を分けたい場合(建築だけしたい人、運営を手伝ってくれる人など)は、OPコマンドだけでなく**LuckPerms**のような権限管理プラグインを使うと、段階的な権限設計ができます。

### 2. シンプルな方法: OP レベル

人数が少なく、信頼している友人だけなら、Minecraft標準のOPシステムで十分なことも多いです。

```bash
docker compose exec mc rcon-cli op <プレイヤー名>
docker compose exec mc rcon-cli deop <プレイヤー名>
```

OPには4段階のレベルがありますが、`itzg/minecraft-server` イメージでは環境変数で細かく制御できます。

```yaml
environment:
  OPS: |
    admin_mcid
  # OPSFILE で複数人・レベル指定も可能
```

**弱点**: OPは基本的に「全権限を持つか、持たないか」の二値に近く、細かい権限分けが苦手です。「ビルドはできるが他人のインベントリは見れない」のような制御にはLuckPermsが必要になります。

### 3. LuckPerms 導入

```yaml
environment:
  SPIGET_RESOURCES: "28140"   # LuckPermsのSpigotMC ID
```

導入後、権限グループを作って割り当てます。

```bash
# グループ作成
docker compose exec mc rcon-cli lp creategroup builder
docker compose exec mc rcon-cli lp creategroup moderator

# 権限付与
docker compose exec mc rcon-cli lp group builder permission set minecraft.command.give false
docker compose exec mc rcon-cli lp group moderator permission set minecraft.command.kick true
docker compose exec mc rcon-cli lp group moderator permission set minecraft.command.ban true

# プレイヤーをグループに割り当て
docker compose exec mc rcon-cli lp user <プレイヤー名> parent add builder
```

#### 設計例

| グループ | できること |
|---|---|
| `default` | 通常プレイのみ |
| `builder` | クリエイティブ関連コマンドの一部を許可 |
| `moderator` | kick/ban、CoreProtectのロールバック権限 |
| `admin` | 全権限(OPと同等) |

### 4. 権限とバックアップの関係

権限を誤って剥奪・付与してトラブルになった場合でも、`05-backup.md` のワールドバックアップとは別に、LuckPermsの設定ファイル自体もバックアップ対象に含めておくと安心です。

```bash
# backup.sh の対象に追加(既存のdataディレクトリに含まれていれば対応不要)
# LuckPermsの設定は通常 ./data/plugins/LuckPerms/ に保存される
```

バックアップ（`itzg/mc-backup` + `rclone`。[05-backup.md](05-backup.md)）は `plugins/` ディレクトリごと含んでいるため、追加設定なしでLuckPermsの権限データも一緒にバックアップされます。

### 5. 運用上の推奨

友人が数人程度の身内サーバーであれば、**最初はOPレベルの運用で十分**です。「特定の人にだけ何かを制限したい」という具体的な要望が出てきたタイミングでLuckPermsを追加する、という順序が手戻りが少ないです(これはDashboardやLoggingの導入判断と同じ考え方です)。

## チェックリスト

```text
[ ] ONLINE_MODE=true を確認
[ ] ホワイトリスト設定・友人のMCID登録
[ ] CoreProtect導入(誤破壊の巻き戻し用)
[ ] OPの付与方針を決定(誰に、どのレベルまで)
[ ] (必要であれば)LuckPerms導入・グループ設計
[ ] plugins/ ディレクトリがバックアップ対象に含まれているか確認
```
