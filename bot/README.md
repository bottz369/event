# BOTTZ AI — LINE Bot(アー写更新)

event-app の最初の実用 LINE Bot 機能。LINE グループで
`@BOTTZ AI ○○のアー写更新` と送り、続けて画像を送ると、アーティスト `○○` の
アー写(画像)を差し替えます。既存 `services/artist_service` をそのまま再利用し、
DB/画像ロジックは新規に書きません(§40 モノリス Bot)。

## 構成

- `bot/main.py` … FastAPI Webhook 本体
  - `POST /callback` … LINE Webhook 受信口(署名検証 → ガード → ルーティング)
  - `GET /` … ヘルスチェック
- LINE 連携は素の HTTP(`requests` + 標準ライブラリ `hmac/hashlib/base64`)で実装
  (§40 で許可された「生 HTTP」。依存最小化 & 純関数のユニットテスト容易化のため)。

### フロー(§40 B4)

1. テキスト `@BOTTZ AI ○○のアー写更新` 受信
   → 署名検証 → ガード通過 → 名前 `○○` を抽出 → `pending[userId]=(名前, 時刻)` を
   メモリ保持(TTL 5 分)→「画像を送ってください」と返信。
2. 同じ userId から画像受信
   → 直近 5 分の pending があればその名前で処理:
   画像 DL → `get_artists_by_names` で特定 → `update_artist`(画像のみ差し替え・名前は既存維持)
   → pending 消去 →「○○ のアー写を更新しました」/「○○ が見つかりません」と返信。
3. pending の無い画像・非許可ユーザーのDMは無視。

### ガード(B-4 以降)

- グループ発イベント、または `OWNER_USER_IDS` に登録された本人の個人トーク（ルームは無視）
- グループのテキストのトリガーは自ボット宛メンション必須(`mention.mentionees[].isSelf == true`)
  ※ @All は `isSelf` が立たないので反応しない
- **そのグループが「起動済み」であること**。起動は `OWNER_USER_IDS` の人が
  「@Bot 起動」と送ると有効になる。未起動グループには使い方のヒントだけ返す。
- 起動後は、そのグループの参加者なら誰でも利用できる(送信者の OWNER ゲートは無し)。

起動状態は Supabase Storage の `bot/activated_groups.json` に永続化される
(Railway の再デプロイ・再起動でも保持。DB スキーマは使わない)。
オーナーがグループを退会すると自動で無効化され、再開はオーナーの「起動」で行う。

> ⚠️ **`ALLOWED_GROUP_IDS` は B-4 でゲートに使われなくなった**。
> env に残っていても無害だが、混乱を避けるなら空にしてよい。

## 環境変数

`bot/.env.example` を参照。ローカルは `bot/.env` にコピーして実値を入れる
(`.env` は `.gitignore` 済み・コミットしない)。Railway では Variables に設定。

| 変数 | 用途 |
| --- | --- |
| `SUPABASE_DB_URL` | 本番 Supabase Postgres 接続 URL(`database.py` が env 経由で読む) |
| `SUPABASE_URL` | Supabase プロジェクト URL(Storage) |
| `SUPABASE_KEY` | Supabase API キー(Storage) |
| `LINE_CHANNEL_SECRET` | 署名検証 |
| `LINE_CHANNEL_ACCESS_TOKEN` | reply / 画像 DL |
| `OWNER_USER_IDS` | **グループを「起動」できる人の userId**(カンマ区切り)。B-4 の起動可否判定に使う |
| `ALLOWED_GROUP_IDS` | ~~反応を許可する groupId~~ **B-4 で未使用**(起動ストアが置き換えた)。空でよい |
| `EVENT_API_KEY` | read 専用 `/api/*` の認証キー(`Authorization: Bearer <key>` / `X-API-Key` で照合。Webhook の LINE 署名検証とは別系統) |
| `ANTHROPIC_API_KEY` | 記入テンプレの LLM 解析(段階C C-1・§52)。**未設定でも Bot は起動する**が、テンプレ解析だけが「解析機能が未設定です」と案内して終わる |

`EVENT_API_KEY` は Railway では他の変数と同じく Variables に設定する。ローカルで `/api` を叩くときは
`export EVENT_API_KEY='任意の長いランダム文字列'` してから uvicorn を起動する(未設定だと `/api/*` は全て 401)。

## ローカル起動

> ℹ️ **Bot には root + bot の両方を install する(full install)。**
> `bot/requirements.txt` は Webhook の追加分だけなので、これ単体では Bot は動かない。
> `bot.main` は共有コードを import する(`bot.main` → `services.artist_service` → `models` →
> pandas 等、`database` → sqlalchemy / supabase 等)ため、アプリ本体の依存一式が必要。
> Docker(Railway)も同じく root + bot を full install する。
> なお streamlit 1.59.2(starlette>=0.46 必須)と fastapi 0.115.6(starlette<0.42)は**版数で両立不可**で、
> 同一環境では starlette が 0.41.3 に固定され streamlit の import は失敗する。root に streamlit が入っていても、
> **Bot が streamlit を import しなければ問題ない**(read 経路は非依存化済み。詳細は開発知見.md §42・罠39)。

```bash
# venv を作る(アプリ用 .venv をそのまま使ってもよい)
python3 -m venv .venv-bot
. .venv-bot/bin/activate
pip install -r requirements.txt -r bot/requirements.txt   # root(本体一式)+ bot(追加分)

# .env を用意(実値は各自)
cp bot/.env.example bot/.env
#  → bot/.env を編集

# 起動(bot/.env を読み込む)
set -a; . bot/.env; set +a
uvicorn bot.main:app --host 0.0.0.0 --port 8000
# ヘルスチェック: curl localhost:8000/
```

LINE の実疎通確認はローカルだと Webhook URL(HTTPS 公開)が必要なため、
`ngrok http 8000` 等でトンネルするか、Railway デプロイ後に行う。

## Railway デプロイ

1. Railway で新規プロジェクト → この GitHub リポジトリを接続。
2. ビルドはルートの **`Dockerfile`** が担当する(Railway は Dockerfile があればそれを使う)。
   ベースは `python:3.13-slim`(本番 Streamlit Cloud と同じ Python)。
   Dockerfile は `pip install -r requirements.txt -r bot/requirements.txt` で
   root(本体一式)+ bot(追加分)の両方を install し(Bot は共有コード
   `services` → `models` → pandas 等を import するため本体依存が必要)、
   `uvicorn bot.main:app --host 0.0.0.0 --port ${PORT}` で起動する。
   ※ streamlit 1.59.2(starlette>=0.46 必須)と fastapi 0.115.6(starlette<0.42)は**版数で両立不可**
   (starlette が 0.41.3 に固定され streamlit の import は失敗する)。Bot イメージに root の streamlit が入っていても、
   **Bot の import 連鎖が streamlit を引かなければ問題ない**(read 経路は非依存化済み。開発知見.md §42・罠39)。
3. Railway の **Custom Start Command は空**にして Dockerfile の CMD を使わせる
   (設定が残っていると `$PORT` が展開されず起動失敗する。開発知見.md 罠36)。
4. Variables に上記環境変数を全て設定。
5. デプロイ完了後の公開 URL(例 `https://xxxx.up.railway.app`)の `/callback` を
   LINE Developers の Webhook URL に設定 → Verify。
6. LINE 側: 応答メッセージ(自動応答)OFF・あいさつ OFF・グループ参加 ON。
7. Bot を対象グループに招待し、`OWNER_USER_IDS` に自分の userId を入れて実機テスト。

### userId / groupId の確認方法

Webhook を一度受けると `bot/main.py` のログに載らないため(ガードで静かに無視)、
初期設定時は Railway のログで受信 payload を確認するか、LINE の Webhook 検証イベントや
公式ツールで `userId` / `groupId` を控えてから env に設定してください。

## テスト

純関数(署名検証・名前抽出・pending TTL)は DB 非依存でユニットテスト済み:

```bash
python3 -m pytest tests/test_bot_line.py -v
```

実アーティストのアー写更新テストは本番データ保護のため、谷内さんの実機テストでのみ実施します。


## オーナー本人の個人トークでのテスト

`OWNER_USER_IDS` に設定された本人は、Botとの個人トークでメンションなしの「アー写変更」「フライヤー」「再生成」「新規作成」や概要を送れる。起動済みグループへのメンションと同じイベント選択・アーティスト選択・確認ボタン・画像処理を使用する。個人トークの「起動」は既に利用可能という返信になり、グループの起動状態には触れない。オーナー以外の個人トークは、文字・画像・ボタンのいずれも無視する。許可者を谷内さんだけにする場合は `OWNER_USER_IDS` を谷内さんのLINE userIdだけに設定する。

個人トークの画像待ちはグループの画像待ちと別に管理する（同じ5分TTL）。テスト用の処理も実際のアーティスト画像やプロジェクトを更新するため、テスト用プロジェクト・画像を選択する。個人トークの返信はそのトークだけに送り、グループへの通知は追加しない。グループでは従来どおり起動とメンションが必要。


## 本人DMの「AIおまかせ制作」

個人トークで「AIおまかせ制作」と送信して始める。`OWNER_USER_IDS` の本人のみ利用可能。通常のグループ操作・Webアプリの手動制作はそのまま使える。

1. 公演概要を送信する。送り直す時は「概要: 本文」。
2. PDF・Excel（.xlsx）・CSVを**ファイル**として添付する。10MB以下。対応範囲はWebのAIおまかせ制作と同じ。控室などを出演・物販データへ取り込まない。
3. 「デザイン: 光 放射状 青 紫」などと送信する。標準ロゴを使い、アプリで設定した標準制作テンプレートを読み込む。
4. 「資料をAIで解析」を押す。概要・資料・訂正をOpenAIへ送信し、API料金が発生する。読み取り結果の日付・料金・出演者掲載順・各部の時刻・出演順・物販・注意事項をLINEで確認する。
5. 修正があれば「訂正: OPENは10:20」のように送り、もう一度解析する。「部数: 1,3」で取り込む部を選べる。1部だけなら通常イベント。名前を照合する場合は「名寄せ: 原文名=>登録名」。
6. 「確認して生成」を押すと、日付・料金・出演順・時刻・名前を確認済みとして制作を進める（必須確認）。AI背景や背景に合わせるロゴ配色には追加API料金が発生する。
7. グリッド版とタイムテーブル版が個人トークへ届く。「保存する」で素材と新規プロジェクトを保存する。保存後はアプリでも編集できる。既存プロジェクトの上書きはしない。

素材を自分で用意する場合、「背景画像を送る」「ロゴ画像を送る」の後に画像を送る。透過ロゴはPNGをファイルで送る。「背景参考画像を送る」の後に送った画像は、AI背景の構図参考だけに使う。「ロゴ色: 背景に合わせる」「ロゴ色: ゴールド」なども指定できる。同じ条件の背景・AIロゴ配色は下書き内で再利用し、配置修正の再試行時に繰り返し生成しない。

「確認」で現在の内容・画像・保存結果を再表示、「中止」で制作を終了する。内容変更後は前の確認ボタンを無効にする。処理中の連打を抑止し、同一Webhookは再処理しない。画像配信が失敗しても完成データを保持して「確認」で再配信し、再度画像生成しない。保存結果が不明な場合は自動再保存せず、アプリの一覧で確認する。

### Bot側の接続設定・運用

- Railway Variablesに `OPENAI_API_KEY` が必要。WebアプリのStreamlit SecretsはBotへ自動共有されない。APIキーはLINEへ送らない。本人のLINE userIdによる制限を使うため、AI利用コードの送信は不要。
- 下書きはユーザーごとのメモリに保持（最大4人・最終操作から2時間・1プロセス）。再起動・デプロイで未保存の下書きは失効する。保存済みプロジェクトは残る。古い下書きボタンからの生成・保存は拒否する。現行の1レプリカ・単一ワーカー構成で利用する。
- 長時間処理は受付をreplyですぐ返し、完了後の結果を本人へのpushで通知する。LINE側の送信枠を使用する。通知に失敗した時は「確認」で取り直せる。
- 下書き画像もLINE配信用に既存の生成画像Storageへ保存する。正式なロゴ・背景アセットとプロジェクトの登録は「保存する」まで実行しない。
- 通常のアー写更新待ちとAI制作は混在させない。AI制作へ入った場合は本人DMの古いアー写更新待ちを解除する。グループ側の待ちは維持する。

自動テスト（有料API・LINE送信・更新・保存をモック化）:

```bash
.venv/bin/python -m pytest tests/test_bot_line.py tests/test_bot_flow.py tests/test_bot_intake.py tests/test_bot_api.py tests/test_bot_auto_production.py -q
```

### 既存プロジェクトの comingsoon 編集

個人トークではオーナー本人、起動済みグループではBotへのメンションで利用できます。
「comingsoonにする」「comingsoonを解除する」でイベント→出演枠をボタンで選び、
「確定して画像を更新」を押すと保存・再生成します。
「花いろはをcomingsoonにして」「花いろはのcomingsoonを解除して」のような完全一致の名前指定も可能です。
複数部の出演枠は部ごとに選択します。選択は本人・トークに紐づき、10分で失効します。
元の登録名とアー写は保持し、解除すると戻ります。
