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
3. pending の無い画像・非許可ユーザー・DM は無視。

### ガード(全て満たす時のみ実行)

- グループ発イベント(DM は完全無視)
- 送信者 `userId` が `OWNER_USER_IDS` に含まれる
- テキストのメンションで自ボット宛(`mention.mentionees[].isSelf == true`)
- `ALLOWED_GROUP_IDS` が設定されていれば `groupId` がその集合に含まれること
  (空なら全グループ許可・送信者ガードは常に有効)

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
| `OWNER_USER_IDS` | 更新を許可する送信者 userId(カンマ区切り) |
| `ALLOWED_GROUP_IDS` | 反応を許可する groupId(カンマ区切り・空可) |
| `EVENT_API_KEY` | read 専用 `/api/*` の認証キー(`Authorization: Bearer <key>` / `X-API-Key` で照合。Webhook の LINE 署名検証とは別系統) |

`EVENT_API_KEY` は Railway では他の変数と同じく Variables に設定する。ローカルで `/api` を叩くときは
`export EVENT_API_KEY='任意の長いランダム文字列'` してから uvicorn を起動する(未設定だと `/api/*` は全て 401)。

## ローカル起動

> ℹ️ **Bot には root + bot の両方を install する(full install)。**
> `bot/requirements.txt` は Webhook の追加分だけなので、これ単体では Bot は動かない。
> `bot.main` は共有コードを import する(`bot.main` → `services.artist_service` → `models` →
> pandas 等、`database` → sqlalchemy / supabase 等)ため、アプリ本体の依存一式が必要。
> Docker(Railway)も同じく root + bot を full install する。
> streamlit 1.59.2 と fastapi 0.115.6 は共存可能なので、root の streamlit が入っていても問題ない。

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
   ※ streamlit 1.59.2 と fastapi 0.115.6 は共存可能(starlette 0.41.3・競合なし)なので、
   Bot イメージに root の streamlit が入っていても無害。
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
