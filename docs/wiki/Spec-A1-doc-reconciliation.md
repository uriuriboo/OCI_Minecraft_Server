<!-- このページは docs/spec/A1-doc-reconciliation.md から生成しています。直接編集しないでください。
     修正は docs/spec/ 側に入れて `python scripts/sync-wiki.py` を実行してください。 -->

# A1. 手順書との差分記録

[docs/manual/](../blob/main/docs/manual) の手順書は構築作業の記録として保存している。コード化の過程で見つかった不整合・バグは判明の都度 `docs/manual/` 側にも直接反映している（過去は「原本のまま無変更保存」としていたが、手順書自体の正確さを優先する方針に変更した）。それでも記述が食い違う場合は `docs/spec/` とコードを正とする。

このページはその全件を、**どちらを正としたか**と理由とともに記録する。手順書側を修正済みの項目は行番号の引用を外している（修正で行がずれるため）。

## 1. 手順書に実体がなかったもの（解決済み）

`docs/manual/02-terraform.md` の旧ドラフトには `# (既存の内容のまま)` とだけ書かれ、実体がどこにも存在しなかった箇所があった。復元根拠を示す。**現在は `02-terraform.md` 自体を実装 (`terraform/`) への短い案内に置き換え、ドラフトのコードは削除した。**

| 対象 | 復元元 | 現在の正 |
| --- | --- | --- |
| `docker-compose.yml` | [08-exposure-options.md](../blob/main/docs/manual/08-exposure-options.md) の方式A/B | `terraform/templates/docker-compose.yml.tftpl` |
| mc-monitor の `.env` | `monitor.py` が読む変数から確定 | `terraform/templates/mc-monitor.env.tftpl` |
| `mc-monitor.service` | [04-monitoring.md:269-279](../blob/main/docs/manual/04-monitoring.md#L269-L279) の「Type=oneshot」記述 | `monitor/systemd/mc-monitor.service` |
| `mc-monitor.timer` | [04-monitoring.md:285-289](../blob/main/docs/manual/04-monitoring.md#L285-L289) の `OnBootSec` / `OnUnitActiveSec` | `monitor/systemd/mc-monitor.timer` |
| `requirements.txt` | (旧ドラフトの `pip install` 行) | `monitor/requirements.txt` (バージョン固定を追加) |

## 2. 手順書どうしの不整合（解決済み・修正を manual に反映）

| # | 内容 | 採用 | 理由 |
| --- | --- | --- | --- |
| 2-1 | Tailscale ACL のタグ名が2種類あった。`03-post-setup.md` は `tag:server` / `tag:friend`、[03b-tailscale-acl.md:84-118](../blob/main/docs/manual/03b-tailscale-acl.md#L84-L118) は `tag:mc-*` / `group:mc-friends` | **03b 版** | 03b が専用の章で詳細に設計されており、[08-exposure-options.md:262-303](../blob/main/docs/manual/08-exposure-options.md#L262-L303) も 03b 版を「完成形」として再掲している。cloud-init の `--advertise-tags=tag:mc-server` も 03b 側と整合する。`03-post-setup.md` 側の ACL 例は削除し、03b への参照に置き換えた |
| 2-2 | `09-server-management.md` が「`06-backup.md の restic backup ./data`」を参照していたが、[06-backup.md:46-56](../blob/main/docs/manual/06-backup.md#L46-L56) の実装は `itzg/mc-backup` + `rclone` で restic は登場しない | **`itzg/mc-backup`** | 06 が実装の章。09 の記述は別構成からの転記と判断した。結論 (`plugins/` を含むので追加設定不要) は変わらない。09 側の記述を修正した |
| 2-3 | [03b-tailscale-acl.md:48-58](../blob/main/docs/manual/03b-tailscale-acl.md#L48-L58) がタグ別 Auth Key への分割を要求していたが、旧 `02-terraform.md` ドラフトの `variables.tf` は単一の `tailscale_authkey` のままだった | **分割する** | 単一キーではタグを出し分けられず、ACL の `ssh` ブロックが一致しない。`terraform/variables.tf` は `tailscale_authkey_server` / `tailscale_authkey_monitor` に分けている（旧ドラフトは削除済み） |
| 2-4 | `00-overview.md` のドキュメント構成表に `03b` と `09` が載っていなかった | **実ファイルを正** | 表が後から追加された章を反映していなかっただけ。追記した |
| 2-5 | `00-overview.md` が「00. 構成概要（差分）」「該当箇所を置き換え」と書かれていた | **本文を正** | 差分として書かれた文書がそのまま本体になっていた。見出しと保存先の注記を修正した |

## 3. 手順書のコードにあったバグ（解決済み・manual は修正または削除で反映）

| # | 内容 | 影響 | 修正 |
| --- | --- | --- | --- |
| 3-1 | 旧 `02-terraform.md` ドラフトの `data "oci_identity_tenancy" "current" { tenancy_id = var.compartment_ocid }` | コンパートメントがテナンシールートでない限り apply が失敗する。動的グループとポリシーはテナンシールートにしか作れない | `tenancy_ocid` 変数を新設し、`iam.tf` はそれを参照する（旧ドラフトは削除済み） |
| 3-2 | 旧 `02-terraform.md` ドラフトの Monitoring プラグイン有効化が `mc_server` にしかなかった | mc-monitor のメトリクスが取れず、[05-dashboard.md:20](../blob/main/docs/manual/05-dashboard.md#L20) が言う「2台の比較表示」ができない | `terraform/compute.tf` は `mc_monitor` にも `agent_config` を付与している（旧ドラフトは削除済み） |
| 3-3 | 旧 `02-terraform.md` ドラフトの `home_ip_cidr` に既定値 `""` があり、`enable_home_ssh = true` との組み合わせを検証していなかった | 空のまま apply すると NSG ルールの `source` が不正になり、途中で失敗する | `terraform/variables.tf` に変数をまたぐ `validation` を追加 (Terraform 1.9 以降の機能)。旧ドラフトは削除済み |
| 3-4 | [04-monitoring.md:180-193](../blob/main/docs/manual/04-monitoring.md#L180-L193)（修正済み）で、メトリクスが `None` のとき `state[key]` を書かずに `continue` していた | メトリクス取得が一時的に失敗すると状態が失われ、次回取得できた時に「初回超過」として**同じアラートが再送される** | `None` のときは前回の状態を引き継ぐよう manual と `monitor/monitor.py` の両方を修正した |
| 3-5 | 旧 `02-terraform.md` ドラフトの `lifecycle` が `source_details[0].source_id` のみを無視していた | `metadata` の変更 (= tfvars の変更) でインスタンスが置換され、**ワールドが消える** | `terraform/compute.tf` は `ignore_changes = [metadata, source_details[0].source_id]`。詳細は [02. アーキテクチャ](Spec-02-architecture)。旧ドラフトは削除済み |
| 3-9 | `01-prerequisites.md` の手順5が「VM 2台共通の Reusable キーを1本発行する」という手順になっていた | `terraform/variables.tf` は最初の `terraform apply` から `tailscale_authkey_server` / `tailscale_authkey_monitor` の2本のタグ付きキーを要求する。タグ付きキーの発行には ACL の `tagOwners` が先に必要で、単一の無タグキーでは `terraform.tfvars` を満たせない | 手順5を「先に ACL の `tagOwners` を登録し、mc-server用/mc-monitor用の2本を発行する」に修正し、[03b-tailscale-acl.md](../blob/main/docs/manual/03b-tailscale-acl.md) 手順3への参照を追加した |
| 3-10 | `04-monitoring.md` に貼られていた `monitor.py` の全文コピーが `RCON_PORT` を `int(os.environ["RCON_PORT"])` で読んでいた | 実装 (`monitor/monitor.py`) は `os.environ.get("RCON_PORT", "25575")`。コピーの通りに動かすと `.env` に `RCON_PORT` がない環境で `KeyError` になる | **全文コピーを削除し、[monitor/monitor.py](../blob/main/monitor/monitor.py) への参照に置き換えた**（旧 `02-terraform.md` のコードを削除したのと同じ理由）。実装をコピーしている限り同じずれが再発する |
| 3-8 | [08-exposure-options.md](../blob/main/docs/manual/08-exposure-options.md) の playit セットアップ手順が「`PLAYIT_SECRET_KEY` を空で `docker compose run --rm playit` を実行し、出てくる認証URLで紐付けてからキーを取得する」という流れになっていた | playit-agent の `docker/entrypoint.sh` が読むのは `SECRET_KEY` であり (`PLAYIT_SECRET_KEY` ではない)、かつ空だと認証URLを出さずに `exit 1` する。`env_file` 経由の受け渡しでも変数名の不一致で届かない | `docker-compose.yml.tftpl` の playit サービスを `environment: SECRET_KEY: "$${PLAYIT_SECRET_KEY}"` に変更 (docker compose の `.env` 変数展開経由)。manual の手順も「playit.gg の docker 向けセットアップウィザードで先にキーを発行する」に修正した |

### 3-6. 改行コード (CRLF) による破壊

手順書には存在しないが、コード化の過程で実際に踏んだ問題。**手元の改行コードがそのまま本番の不具合になる**。

`core.autocrlf = true` の Windows でクローンすると、テンプレートが CRLF でチェックアウトされる。cloud-init の `write_files` はテンプレートの中身をそのまま VM に埋め込むため、CRLF が VM 上のファイルに入り込む。

| ファイル | CRLF だとどうなるか |
| --- | --- |
| `backup.sh` | 行継続の `\` が `\r` をエスケープしてしまい `syntax error near unexpected token '\|'` |
| `playit-check.sh` | `unexpected end of file` |
| `.env` | 値の末尾に `\r` が付く。**RCON 認証が理由の分からない失敗をする** |
| `*.service` / `*.timer` | systemd が `ExecStart` の値を誤読する |
| `monitor.py` | shebang が `python3\r` になり直接実行できない |

対策を3層にした。1層だけでは、別の端末でクローンしたときや zip でダウンロードしたときに再発するため。

| 層 | 実装 | 効果 |
| --- | --- | --- |
| 1. リポジトリ | `.gitattributes` の `* text=auto eol=lf` | どの環境でも LF でチェックアウトされる |
| 2. レンダリング時 | `terraform/render.tf` の `replace(x, "\r\n", "\n")` | `.gitattributes` が効かない環境でも落とす |
| 3. 検査 | `scripts/check-consistency.py` の改行コード検査 | 混入をコミット前に止める |

この問題は最初の検証で見逃していた。PowerShell から WSL の `bash -n` を呼ぶ際のクォート処理が壊れており、**`bash -n` が実際には実行されていなかった**。検証コマンド自体が期待通り動いているかを確認する必要がある、という教訓である。

### 3-7. Terraform テンプレートのエスケープ

手順書には存在しないが、コード化の過程で判明した注意点。Terraform の `templatefile` がエスケープとして扱うのは `$${` と `%%{` **だけ**である。

| 書き方 | レンダリング結果 | 用途 |
| --- | --- | --- |
| `$${VAR}` | `${VAR}` | docker-compose の変数展開、シェルの変数参照 |
| `$(cmd)` | `$(cmd)` (そのまま) | シェルのコマンド置換 |
| `$((expr))` | `$((expr))` (そのまま) | シェルの算術展開 |
| `$$((expr))` | **`$$((expr))`** | 誤り。bash では `$$` が PID に展開される |
| `{{.Field}}` | `{{.Field}}` (そのまま) | Go テンプレート (docker inspect) |

`$$((...))` は当初 `backup.sh.tftpl` に書いてしまい、レンダリング結果の確認で検出した。静的検証の項目に「`backup.sh` の `$((...))` が残っているか」を入れている理由である ([09. 検証方法](Spec-09-verification))。

## 4. 意図的な設計変更

手順書のやり方を変えた箇所。手順書が間違っていたわけではなく、方針を変えた。

| # | 手順書 | 現在 | 理由 |
| --- | --- | --- | --- |
| 4-1 | cloud-init は方式B (Tailscale) の iptables を直書き (旧 `02-terraform.md` ドラフト、削除済み) | `exposure_mode` で3方式を切り替え | [08-exposure-options.md](../blob/main/docs/manual/08-exposure-options.md) が3方式を提示しているのに、コードが1つに固定されていた |
| 4-2 | `monitor.py` の `FILESYSTEM_NAME` をハードコードし、実測後にコードを編集 ([04-monitoring.md:49-50](../blob/main/docs/manual/04-monitoring.md#L49-L50)) | 環境変数化し、`filesystem_name` 変数から生成 | 実測値の反映のたびに Python を編集するのは、変更経路として不適切 |
| 4-3 | `THRESHOLDS` をコード内の定数とし、変更はコード編集 ([07-operations.md:80-82](../blob/main/docs/manual/07-operations.md#L80-L82)) | 環境変数で上書き可 (既定値は手順書と同じ) | 同上 |
| 4-4 | `rclone config` を対話で設定 ([06-backup.md:9-30](../blob/main/docs/manual/06-backup.md#L9-L30)) | `rclone.conf` をテンプレートから生成 | 対話は再現できない。`no_check_bucket = true` も追加 (R2 で PutObject が 501 になることがある) |
| 4-5 | バックアップは R2 のみ ([06-backup.md](../blob/main/docs/manual/06-backup.md)) | R2 + OCI Object Storage の二重化 | `todo.md`「R2だけでなく、OCIにもバックアップを作成」 |
| 4-6 | `rclone sync` ([06-backup.md:56](../blob/main/docs/manual/06-backup.md#L56)) | `rclone copy` + `--min-age` による削除 | `sync` はローカルの世代削除をクラウドまで波及させる。手元のバグでバックアップを失う経路を切った。理由は [05. バックアップ](Spec-05-backup) |
| 4-7 | 世代管理の記述なし | ローカル7世代 + クラウド30日 | ブートボリューム 100GB と無料枠 (R2 10GB / OCI 20GB) を超えないため |
| 4-8 | OCI へのバックアップ手段の記述なし | インスタンスプリンシパル + バケット限定ポリシー | VM 上に OCI の鍵を置かない。侵害時の影響範囲を1バケットに限定する |
| 4-9 | `playit-check.sh` の Webhook URL をプレースホルダで手書き ([08-exposure-options.md:157-169](../blob/main/docs/manual/08-exposure-options.md#L157-L169)) | テンプレートから生成、`crontab -l` 操作ではなく `/etc/cron.d/` に配置 | `crontab -l \| crontab -` は冪等でなく、cloud-init の再実行で重複する |
| 4-10 | 復元は手順を手で実行 ([06-backup.md:79-95](../blob/main/docs/manual/06-backup.md#L79-L95)) | `scripts/restore.sh` | `tar -tzf` での事前検証と、`data.broken.<日時>` への退避を追加。**壊れたアーカイブで上書きしない**ため |
| 4-11 | ZeroTier は選択肢の説明のみ ([08-exposure-options.md:321-352](../blob/main/docs/manual/08-exposure-options.md#L321-L352)) | `enable_zerotier` で Tailscale と併設可能 | `todo.md`「tailscaleを使うときはzerotierも入れること」 |
| 4-12 | `unattended-upgrades` を手で `dpkg-reconfigure` ([07-operations.md:41-45](../blob/main/docs/manual/07-operations.md#L41-L45)) | cloud-init で `/etc/apt/apt.conf.d/20auto-upgrades` を配置 | 対話を避ける |
| 4-13 | OCI CLI の記述なし | cloud-init で `/opt/oci-cli` に venv + pip | 公式 install.sh は対話が入る |
| 4-14 | Ansible は将来の拡張候補 ([07-operations.md:88](../blob/main/docs/manual/07-operations.md#L88)) | day-2 更新のみを担う最小構成として導入 | cloud-init 単独では VM 再作成なしに更新できない。全面移行はしない |
| 4-15 | ダッシュボードはコンソールで手作成 ([05-dashboard.md](../blob/main/docs/manual/05-dashboard.md)) | `dashboards/oci-dashboard.json` + `scripts/print-dashboard.py` | OCID の手書きを避ける。パネル構成は別リポジトリの Grafana 構成 (旧 `monitor_sample/`、削除済み) を参考にした |
| 4-16 | サンプルファイルの命名は未定義 | `*_sample` (例: `terraform.tfvars_sample`) | 既存の `monitor_sample/.env_sample` (別リポジトリ、削除済み) の命名に合わせた |
| 4-17 | mc-monitor の Python を `python3 -m venv` + `pip install` (旧 `02-terraform.md` ドラフト、削除済み) | uv (`uv venv` + `uv pip sync`) | `todo.md`「pythonはuvで管理」。1/8 OCPU の Micro VM では pip の依存解決が遅く cloud-init のタイムアウトに近づく。uv は venv 作成を自前で行うので `python3-venv` も不要になった |
| 4-18 | 依存を `requirements.txt` に直接書く | `pyproject.toml` に宣言し `uv pip compile` で生成 | 推移的依存までピン留めされる。直接依存と固定版を同じファイルで管理すると、どちらを直すべきか分からなくなる |
| 4-19 | OCI CLI の記述なし (4-13 で venv + pip にした) | `uv tool install oci-cli` | 同上。venv の管理が不要になり、`backup.sh` のパスも `/usr/local/bin/oci` に単純化された |
| 4-20 | Terraform の導入方法の記述なし | tenv + `terraform/.terraform-version` | `todo.md`「terraformインストール方法をドキュメントに追加 / scoop install tenvまたはbrew install tenvから」。端末を変えても同じ版で動く |
| 4-21 | バージョンの値を文書に書いていた（`04-monitoring.md` の `monitor.py` 全文、`08-exposure-options.md` の playit のタグ、`07-tech-stack.md` / `A2-toolchain.md` / `08-parameters.md` / `CLAUDE.md` の Terraform の版、`08-parameters.md` の変数の個数） | **値は書かず定義場所だけ書く。** 全文コピーは実装への参照に置き換えた | 1 箇所上げるたびに複数の文書を直すことになり、実際に Terraform の版 (`1.9.8` のまま) と playit のタグ (`0.15` のまま) と変数の個数 (`39` のまま) が古くなっていた。検出は `.claude/skills/doc-drift/` の検査に任せる |

## 4b. セルフホスト構成 (`docker/`) からの取り込み

自宅 Raspberry Pi 向けのセルフホスト構成一式が、一時的に `docker/` に置かれていた (Pi 側の `server/` と、別PCで Grafana を動かす `client/` の2環境)。取り込みの判断を済ませたので**ディレクトリは削除した**。ここがその記録である。

判断の基準は「**OCI のマネージドサービスまたは既存実装で実現済みのコンテナは作らない**」。

| セルフホスト側 | 判断 | 理由 |
| --- | --- | --- |
| `mc-router` | **取り込む** | OCI 側に相当するものがない。playit のアドレスは誰でも接続を試せるため、接続レート制限を PaperMC の前段に置く |
| `backup` (`itzg/mc-backup` 常駐/profile) | 取り込まない | `backup.sh` が同じイメージを都度 `docker run --rm` する。R2 に加えて OCI Object Storage への二次コピーもあり、こちらの方が広い ([05. バックアップ](Spec-05-backup)) |
| `monitor` (`itzg/mc-monitor` の Prometheus exporter) | 取り込まない | `monitor.py` が RCON で TPS・人数・死活を取り `custom_minecraft` に記録する。スクレイプ先がない ([04. 監視](Spec-04-monitoring)) |
| `node-exporter` | 取り込まない | Oracle Cloud Agent が追加実装なしで収集する |
| `victoriametrics` | 取り込まない | OCI Monitoring。1GB の監視VMに時系列DBは載らない |
| `loki` / `promtail` | 取り込まない | ゲームログの集約は対象外 (5章「未実施 / 保留」の OCI Logging と同じ判断) |
| `grafana` (`client/`) | 取り込まない | 可視化は OCI Console Dashboards。パネル構成だけは 4-15 のとおり参考にしている |

コンテナ以外の設定で取り込んだもの。

| 項目 | 取り込んだ理由 |
| --- | --- |
| `stop_grace_period: 1m` | 既定の 10 秒では PaperMC が終了しきれず SIGKILL され、ワールドが壊れうる |
| `logging` の `max-size` / `max-file` | 上限がないと json ログが無制限に育ち、ディスク使用率 80% のアラートを静かに押し上げる |
| `security_opt: no-new-privileges` | 追加コストがない |
| `ENABLE_AUTOPAUSE: "false"` の理由 | 値は元から同じだったが、**なぜ false なのか**の説明がなかった。セルフホスト側のコメント (監視の定期アクセスでアイドル判定がリセットされ、発火しても JVM を SIGSTOP するだけ) を移植した |

取り込まなかった設定。

| 項目 | 理由 |
| --- | --- |
| `playit` の `network_mode: host` | bridge のままにする。`.env` をまるごと渡さず `SECRET_KEY` だけを渡す既存方針 (3-8) と、ホストにポートを出さない方針を維持するため |
| playit-agent のタグ `0.17` | 本構成は `1.0` に固定済み ([07. 構成技術・バージョン](Spec-07-tech-stack)) |
| `VERSION` の固定 | `LATEST` 追従を維持する。固定したくなった場合の手順は [07. 構成技術・バージョン](Spec-07-tech-stack) にある |
| `AUTO_SCALE` の既定有効 | 既定は無効。理由は [02. アーキテクチャ](Spec-02-architecture) の「scale to zero を既定で無効にしている理由」 |
| `group_add` による docker GID の指定 | GID はホスト依存で Terraform の時点に確定しない。`auto_scale` 有効時のみ `user: "0:0"` で動かす |
| `METRICS_BACKEND` / `API_BINDING` | Prometheus がないのでスクレイプ先がない |

## 5. 未実施 / 保留

`todo.md` の項目のうち、意図的に実施していないもの。

| 項目 | 状態 | 判断 |
| --- | --- | --- |
| OCI Resource Manager | 未実施 | 単独運用なら state はローカルで足りる |
| OCI Logging | 未実施 | ゲームログの検索が現状不要 |
| OCI Vault | 未実施 | tfvars で足りている |
| OCI Bastion | 未実施 | Tailscale SSH + シリアルコンソールで足りている |
| OCI Certificates | 未実施 | HTTPS を終端する要素がない |
| バックアップの自動化 | 未実施 | 手動運用で RPO が足りている。理由は [05. バックアップ](Spec-05-backup) |
| Ansible への全面移行 | 意図的にしない | 境界の判断基準は [02. アーキテクチャ](Spec-02-architecture) |

判断の背景は [07. 構成技術・バージョン](Spec-07-tech-stack) の「使っていない OCI サービス」にも記載している。

## 6. 未検証の項目

コード化はしたが、この環境では検証できていないもの。**実環境で確認が必要**。

| 項目 | 検証できなかった理由 | 確認方法 |
| --- | --- | --- |
| `ansible-playbook --syntax-check` | ansible 未インストール、WSL に `python3-venv` がなく、Docker デーモンが停止していた。YAML 構造とモジュール名は静的に確認済み | WSL2 で `apt install ansible-core` 後に実行 |
| `cloud-init schema` による検証 | 同上 (cloud-init コマンドが必要) | レンダリング結果に対して実行。YAML としての妥当性と `write_files` の中身は PyYAML で確認済み |
| OCI リソースの実際の作成 | クラウド認証情報がない | `terraform apply`。`validate` は通っている |
| ダッシュボード JSON | OCI のインポート形式ではなく定義書として作成した | コンソールで手入力して確認 |
| `oci os object bulk-upload` の動作 | 同上 | V-24 |
| `oci_objectstorage_object_lifecycle_policy` の動作 | 同上 | 30日後に古いオブジェクトが消えるか |
