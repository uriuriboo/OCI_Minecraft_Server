<!-- このページは docs/spec/01-requirements.md から生成しています。直接編集しないでください。
     修正は docs/spec/ 側に入れて `python scripts/sync-wiki.py` を実行してください。 -->

# 01. 要件

## 機能要件

| ID | 要件 | 実現方法 | 確認 |
| --- | --- | --- | --- |
| F-01 | 友人が Minecraft サーバーに接続できる | `exposure_mode` で選んだ公開方式 | [09. 検証方法](Spec-09-verification) V-06 |
| F-02 | 管理者が自宅IPの変動に関係なく SSH できる | Tailscale SSH | V-03 |
| F-03 | 許可した Minecraft アカウントだけが参加できる | `ENFORCE_WHITELIST` + `ONLINE_MODE=true` | V-14 |
| F-04 | 友人に段階的な権限を付与できる | OP / LuckPerms | V-16 |
| F-05 | 誤破壊を巻き戻せる | CoreProtect | V-15 |
| F-06 | CPU・メモリ・ディスクの使用率を把握できる | Oracle Cloud Agent → OCI Monitoring | V-08 |
| F-07 | TPS とプレイヤー数を把握できる | monitor.py → カスタムメトリクス | V-11 |
| F-08 | 異常時に Discord へ通知が届く | monitor.py → Discord Webhook | V-10 |
| F-09 | サーバーごと落ちた場合も検知できる | 別VM (mc-monitor) から RCON 監視 | V-12 |
| F-10 | 1画面で状態を確認できる | OCI Console Dashboards | V-13 |
| F-11 | ワールドをバックアップできる | `backup.sh` (手動実行) | V-17 |
| F-12 | バックアップから復元できる | `scripts/restore.sh` | V-18 |
| F-13 | 公開方式を後から切り替えられる | `exposure_mode` の変更 + Ansible 適用 | V-20 |

## 非機能要件

### コスト

| 項目 | 要件 | 根拠 |
| --- | --- | --- |
| N-C-01 | 金銭コストを 0 円に保つ | Always Free 枠内に収める |
| N-C-02 | Arm VM は 2 OCPU / 12GB を超えない | Always Free の Arm 枠は合計 2 OCPU / 12GB（2026-06-15 に 4 OCPU / 24GB から半減）。mc-server がその全量を使う |
| N-C-03 | Object Storage の使用量は 20GB 未満 | Always Free 枠。保持日数で制御する |
| N-C-04 | R2 の使用量は 10GB 未満 / リクエストは月100万回未満 | R2 無料枠 |
| N-C-05 | 課金が不確実なサービスを常用しない | OCI Functions が Always Free 対象か公式に明記されていないため使わない |

### 性能

| 項目 | 要件 | 根拠 |
| --- | --- | --- |
| N-P-01 | TPS 15 以上を維持する | 15 未満で体感的に処理落ちする。これを下回ったらアラート |
| N-P-02 | 同時接続 20 人まで | `mc_max_players`。12GB / 8G ヒープで想定する上限 |
| N-P-03 | 監視VMの負荷は無視できる程度 | 1GB メモリ。常駐せず5分ごとの oneshot 実行にする |

### 可用性

| 項目 | 要件 | 根拠 |
| --- | --- | --- |
| N-A-01 | 冗長化はしない | 遊び用。停止の事業影響がない |
| N-A-02 | VM とコンテナは再起動で自動復帰する | `restart: unless-stopped` |
| N-A-03 | 管理アクセスの経路を常に1つ以上残す | Tailscale → 自宅IP穴 → シリアルコンソールの3段構え |
| N-A-04 | 監視の停止がサーバー稼働に影響しない | monitor.py は読むだけ。止まっても Minecraft は動く |

### セキュリティ

| 項目 | 要件 | 根拠 |
| --- | --- | --- |
| N-S-01 | インターネットからの受信ポートを 0 にする | ポートスキャンの対象にならない |
| N-S-02 | SSH のパスワード認証を無効化する | 総当たりを成立させない |
| N-S-03 | RCON をインターネットに露出しない | 認証が平文プロトコル。VCN 内に閉じる |
| N-S-04 | 秘密情報を VM 上の平文ファイルに最小限しか置かない | バックアップは OCI の鍵を置かずインスタンスプリンシパルで認証する |
| N-S-05 | 秘密情報をリポジトリにコミットしない | `.gitignore` + `*_sample` で投入口を分離する |
| N-S-06 | 友人に管理系ノードを見せない | Tailscale ACL で mc-monitor を `group:mc-friends` から隠す |
| N-S-07 | ネットワーク到達とアカウント認証を二重で絞る | ACL は IP しか見ないため、MCID はホワイトリストで絞る |

### 運用性

| 項目 | 要件 | 根拠 |
| --- | --- | --- |
| N-O-01 | 定期的な手作業を最小化する | OS 更新は unattended-upgrades、監視は自動 |
| N-O-02 | 設定変更で VM を作り直さない | ワールドが消えるため。[06. 運用・保守](Spec-06-operations) の変更管理を参照 |
| N-O-03 | 同じ設定を2箇所で管理しない | 乖離を構造的に防ぐ。[02. アーキテクチャ](Spec-02-architecture) 参照 |
| N-O-04 | クラウドに繋がずに構成を検証できる | `terraform validate` + `scripts/check-consistency.py` |

## 制約

| 制約 | 影響 |
| --- | --- |
| Always Free の Arm 枠は競争率が高く、作成が Out of Capacity で失敗する | `ad_index` を変えて再試行する運用を前提にする |
| OCI は `metadata.user_data` の変更でインスタンスを置換する | cloud-init に頻繁に変わる値を置けない。Ansible を併用する理由 |
| OCI Notifications に Discord 連携がない | Discord 通知は monitor.py に一本化し、OCI アラームはメールに留める |
| Oracle Cloud Agent のメトリクス反映に 5〜10 分かかる | 構築直後の確認時は待つ。監視の初回実行を `OnBootSec=5min` にしている理由 |
| `FilesystemUtilization` の `fileSystemName` は実測でしか分からない | 構築後に確認して設定する項目として切り出す (`filesystem_name`) |
| PaperMC の `/tps` 出力形式はバージョンで変わる | 構築後に実出力を確認する受入試験項目にする (V-09) |
| Ansible は Windows をコントロールノードにできない | WSL2 または mc-monitor 上から実行する。フォールバックのシェルスクリプトも用意する |
| Tailscale のノード再認証期限が切れると SSH できなくなる | Key expiry を無効化する作業を必須手順にする |
