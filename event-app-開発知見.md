# event-app 開発知見ドキュメント

このファイルはローカル版です。フェーズ計画 / 罠コレクション / バグ履歴の
本体は Web Claude のプロジェクト知識として登録されたメイン版にありますが、
ローカルでも参照できるよう以下のセクションを保存します:
- セクション11: LINE Bot 構想の記録
- セクション12: フェーズ3 パフォーマンス改善の成果記録(2026-06-29)

最終更新: 2026-07-10

---

## 11. 将来構想: LINE Bot によるフライヤー制作完全自動化

最終更新: 2026-05-26(打ち合わせベース、実装はまだ先)

### 11.1 構想の概要

依頼者がグループライン経由でフライヤーをオーダーし、LINE Bot がそれを受けて
event-app の機能を呼び出し、フライヤー画像を生成して返す。
谷内さんは「最終承認」のみ行い、定型作業から解放される設計。
依頼者 → グループライン → LINE Bot:「@Bot テンプレ送って」
↓
依頼者がテンプレ埋めて返信
↓
LLM が構造化データに変換
↓
event-app の services層を API として呼び出し
↓
生成された画像を谷内さんに最終確認
↓
OK なら依頼者(グループ)に共有

### 11.2 設計判断(打ち合わせで合意済み)

**テンプレ方式の採用**
- 自由対話方式は曖昧さと実装難易度が高い
- 「右上の3番目を入れ替えて」のような空間指示は人間でも混乱する
- テンプレに項目を埋めて返信する方式が、認知負荷が低く実装も簡単
- 段階1(新規作成のみ)→ 段階2(編集=テンプレ全体再送)→ 段階3(限定的差分指示)で広げる

**グループライン + メンション判定 + DM完全シャットアウト**
- Bot はグループに招待して使う
- メンションされた時だけ反応(雑談の邪魔をしない)
- 個人DMは完全に無視(API コスト防止)
- 谷内さんが事前登録したグループID 以外でも無視
- グループ内でも編集系オーダーは谷内さんのユーザーID 限定

**雑談ターン制限**
- 軽い人格を持たせる(自己紹介、業務外の雑談を優しく打ち切る)
- 雑談3〜5ターンで「業務に戻りましょう」と促す
- API コスト管理と「面白さ」の両立

**最終承認は人間が握る**
- Bot が自動納品ではなく、谷内さん経由で納品
- LLM の誤解釈リスクへの保険
- 谷内さんの「品質チェック」という付加価値が残る

### 11.3 リファクタとの関係

**今のフェーズ2Bリファクタは LINE Bot 化の土台になっている**

- 古いコードは画面UI と DB処理が密結合 → 画面なしで機能を呼べない
- フェーズ2B 以降のアーキテクチャは services層が画面非依存
- リファクタ完遂後、services層を Web API(FastAPI 等)として公開すれば、
  LINE Bot から呼べるようになる
- リファクタを「綺麗ごと」ではなく「LINE Bot 化への実用的投資」と位置づける

### 11.4 想定ロードマップ
現在 → フェーズ2B 完遂(サクサク達成 + 画面非依存の土台完成)
→ フェーズ3〜4(保存経路完全統一、data_json 廃止)
→ 【新規】フェーズA: services層を Web API として公開
→ 【新規】フェーズB: LINE Bot プロトタイプ(段階1: 新規作成のみ)
→ 【新規】フェーズC: 段階2(編集対応)
→ 【新規】フェーズD: 段階3(限定差分指示)+ 自然言語解釈の高度化

### 11.5 実装で参考にするもの

谷内さんが既に作っている「請求書アプリ」に類似機能の実装経験がある。
特に以下のノウハウが転用可能と思われる:
- 認可・許可ユーザー判定の仕組み
- 画像アップロードの扱い
- LLM 呼び出しと構造化データへの変換
- 緊急停止スイッチ等の運用機能

実装フェーズに入る時に、請求書アプリの構造を共有してもらい、
event-app への適用方法を一緒に設計する。

### 11.6 谷内さんの仕事観の理解(重要)

谷内さんはイベンターではなく「依頼を受けてフライヤーを制作する人」。
LINE Bot 化は単なる効率化ではなく「自分の事業の運営方法を再設計する」試み。

- API キー・サーバー・グループID登録、全て谷内さんのコントロール下
- 依頼者からは「谷内さんに依頼している」構造は変わらない
- 谷内さんの作業負担だけが劇的に減る、純粋に得な設計
- 完成後は「同案件数を半分の労力で」or「並行案件数を増やす」を選択可能

### 11.7 LINE Bot 段階計画 v2(2026-07-10 設計セッションで更新)

§11.2〜11.4 の構想を、LIFF 採用の決定を反映して引き直したもの。
旧ロードマップ(§11.4)の「テンプレ方式 段階1〜3」は本計画で置き換える。

#### 決定事項(2026-07-10 合意)

1. **TT の新規作成・修正は LIFF フォームを採用**(テンプレ+LLM解釈 方式は不採用)。
   - 理由: 修正が頻繁かつパターン予測不能。フォームは「TT全体の編集画面」なので
     どの修正にも同一UIで対応でき、LLM誤読リスクとそのAPIコストが原理的にゼロ。
   - 編集時はプリフィル(案件IDをURLに載せ、APIから現状を読み込んで表示)。
     依頼者は差分操作のみ(ドラッグ入替・行挿入・値変更)。全打ち直しは発生しない。
2. **グリッド並び順も LIFF で編集**。サムネイルを実配置どおり表示しドラッグ入替。
   row_counts も調整可。データは grid_order_json の read→表示→write の1往復。
   - TT編集との連動ルール: TT送信時、グリッドは「新規追加者を末尾に追加/
     消えた人を除外」で自動追従(現行アプリのリセットボタンと同思想)。
3. **アー写更新はトーク画像送信**(LIFF不要)。「@Bot バンドAのアー写更新」+画像
   → Storage アップロード → Artist 更新 → 谷内さんに確認通知。
   - 注意: アー写はアーティストDB全体で共有。更新は他イベントのグリッドにも波及
     (通常は正しい挙動。「このイベントだけ旧写真」要望の可能性は頭に置く)。
   - 将来の顔認識キャッシュ導入時は、アー写更新でキャッシュ再計算をトリガーする
     設計が必要。
4. **最終承認は谷内さん**(§11.2 の原則を維持)。Bot骨格の設計
   (グループ許可リスト・メンション判定・DM遮断・雑談ターン制限・軽い人格)も維持。

#### 保留(構想メモのみ・実装計画に含めない)

- **フライヤー背景のAI画像生成**: 「夏っぽく」等の要望に候補2〜4枚生成→依頼者選択。
  コストは1枚 $0.01〜0.13 程度で案件単価比で誤差。文字なし背景のみ生成させ、
  文字入れは既存 Pillow 合成が担う。視認性はスクリム(半透明敷き)+縁取りを
  合成側で保証し、自動コントラスト判定は後追い改善。印刷用途は解像度
  (要アップスケール)に注意。→ 段階B完了後に再検討。

#### 段階計画

**段階0(前提・現在進行中): リファクタ完遂**
- Phase 5 残り(grid B2 + スライスC、flyer ビュー移行)+ Phase 6 仕上げ。
- services 層の Streamlit 依存(@st.cache_* 等)を外し画面非依存化(§12.3 既記載)。
- ここまでは既存フェーズ計画のまま。Bot 作業は一切着手しない。

**段階A: Web API 層(FastAPI 想定)**
- services 層を包む API を公開。最小エンドポイント:
  - TT rows の read / write(プロジェクトID指定)
  - grid_order の read / write
  - アーティスト画像の更新
  - プロジェクト新規作成
  - 画像生成トリガー(TT/グリッド/フライヤー)+ 生成物の取得
- 認証(APIキー or 署名)、案件ID⇔LINEグループID の紐付けテーブル設計。
- ホスティング先の選定(無料枠優先)もここで決定。

**段階B1: Bot 骨格 + 承認フロー**
- グループ許可リスト / メンション判定 / DM完全無視 / 編集系は谷内さんID限定 /
  雑談ターン制限 / 軽い人格(§11.2 のまま)。
- 谷内さんへの承認通知 → OK 返信で依頼者グループへ納品、の承認パイプライン。
- 請求書アプリの認可・緊急停止スイッチ等のノウハウを転用(§11.5)。

**段階B2: LIFF 新規作成(MVP)**
- LIFF フォーム v1: OPEN/START タイムピッカー、アーティスト行の追加・名前入力・
  持ち時間選択・ドラッグ入替。送信 → API → 画像生成 → 承認 → 納品。
- LINE Developers での LIFF 登録、案件IDのURLパラメータ紐付け
  (フォームはグループ外=個人画面で動くため必須)。

**段階B3: LIFF 編集(プリフィル)+ グリッドタブ**
- 既存案件の読み込み表示 → 差分操作 → 送信。
- グリッド並び替えタブ(サムネイル+ドラッグ+row_counts)と TT→グリッド自動追従。

**段階B4: アー写更新(トーク画像送信)**
- メンション+画像添付の受信 → アーティスト特定(名前指定)→ 更新 → 承認通知。
- ※ B2 と順序入替可(LIFF 不要で請求書アプリの経験が直接効くため、
  Bot 骨格の動作確認を兼ねて B1 直後に前倒しする案もある。着手時に判定)。

**段階C(保留分の再検討): フライヤーAI背景生成**
- 上記「保留」メモを再評価。スクリム+縁取りの合成側実装とセットで着手判定。

---

## 12. フェーズ3 パフォーマンス改善(2026-06-29 完了分)

本番 Streamlit Cloud で「1ボタン押下→約60秒グレーアウト・2回押し必要」の
重度パフォーマンス問題を解決した。本番ログ([PERF] 計測)で原因を数値特定して
から、1つずつ別コミット・別デプロイで対処した。罠コレクション / バグ履歴 / 
フェーズ計画の本体は Web Claude プロジェクト知識のメイン版にあるが、新しい罠
3件と将来タスクをここにも控えとして残す。

### 12.1 成果サマリ

| commit | 内容 | 効果 |
|---|---|---|
| `a9a8bb6` | TT/グリッド画像の自動生成廃止(生成はボタン押下時のみ) | プロジェクトを開く時間 約60秒 → 約4.6秒(約13分の1) |
| `df1a52c` | `init_db` / `check_and_migrate_add_goods_columns` を `@st.cache_resource` でプロセス1回化 | 毎再実行の DDL ラウンドトリップを削減 |
| `75797a5` | `use_container_width=True` → `width='stretch'` を28件一括移行 | 非推奨期限切れ地雷の除去 + ログノイズ解消 |
| `50256c5` | `list_projects_for_selector` を `@st.cache_data` 化 + 一覧変更5経路で明示 invalidate | 毎再実行 ~460ms の固定費を、一覧が変わったときだけに削減。`save_active_project` は title/event_date 変化時のみ無効化 |
| `2e8cada` | flyer 配置モード selectbox の widget key を真の SSOT `flyer_time_alignment` に一本化 | 罠10(widget所有keyへの外部書き込み競合)と罠15(`time_alignment_sel` の DB焼き付き)を根治 |

進行プロセス:
1. `de6d52a` で `[PERF]` プレフィックスの計測ログを 24 箇所に挿入(挙動変更なし)
2. 本番ログで `tt_image AUTO generate took 22910 ms` 等の数値を観測
3. 原因を数値で特定してから1つずつ対処、各 commit ごとに本番反映 → ログで効果検証

### 12.2 新しい罠(メイン版 罠コレクションの罠16-18 対応控え)

**罠16: `st.tabs` は「表示中のタブだけ」ではなく全タブの中身を毎再実行で eager に評価する。**
重い処理(画像生成・DDL・DB一覧取得)を各タブ render 内に無条件で置くと、どのタブに
いても毎操作でその全部が走り、致命的に重くなる。重い生成はボタン押下時のみ・
キャッシュ前提で書くこと。
(今回「開くと60秒」の根本原因がこれ。workspace の4タブが eager 評価 → TT/グリッド画像
の自動生成が毎回走っていた。)

**罠17: `@st.cache_data` は速いが、無効化を設計とセットにしないと「最新情報がバグる」
(罠1系)を再発させる。**
一覧/表示が変わる全経路を洗い出し、明示的な `.clear()` を漏れなく仕込むこと。
"速いが古い"(TTL任せ)は不採用。
今回 `list_projects_for_selector` のキャッシュ化では 5 経路(create/duplicate/delete/
孤立削除/save での title/event_date 変化検知)に明示 `clear()` を仕込んだ。

**罠18: widget は `key` と `default`(`index=`/`value=`)を両方持ち、かつ同じ key に
session_state 経由で(間接含む)書き込みがあると二重設定警告が出る。**
解決は widget の key を真の SSOT キーに一本化し、`default` 指定と外部書き込みを
やめること(2 key 並走を作らない)。
今回 `flyer_time_alignment_sel`(widget 所有 key)と `flyer_time_alignment`(真の SSOT)
の 2 key 並走を解消し、widget key を `flyer_time_alignment` に一本化した。

### 罠19: Claude Code の Edit ツールは「大ブロック置換」「コメント置換」で壊れる
Phase 2B-2-d で頻発。61行級のブロック置換や複数行コメントの「置換」を Edit で
やらせると、(a) 撤去本体が実行されず説明コメントだけ挿入、(b) diff 後半が文字欠落、
(c) 古いコメントを消さず新コメントを追記するだけ、といった壊れ方をする。
→ 対処: 大ブロック撤去・コメント/docstring 書き換えは手削除に切り替える。
  Edit が2回連続で同じ壊れ方をしたら3回目を賭けず即・手削除。

### 罠20: Edit の diff は「after(適用後)」が見えないことがある
Edit プレビューが削除前の文脈しか映さず、適用後の姿が確認できないまま Yes を迫る。
この状態で承認すると罠19 の破損を見逃す。
→ 対処: 承認前に sed で range を read-only 表示させ「適用後の想定」を先に文字で出す。
  適用後は grep + py_compile の生出力で確認するまで「完了」扱いにしない。
  書いた要約(「削除61行」等)は信用せず生 grep で裏を取る。

### 罠21: git commit にAI署名/セッションURLが勝手に追記される
Claude Code が commit 時に Co-Authored-By 行と claude.ai/code/session_ URL を
指示なく追記する。公開リポジトリの履歴に個人セッションリンクが焼き付く。
→ 対処: commit メッセージは「指定の1行のみ」を明示し自動追記を禁止。混入したら
  No で破棄し git commit -m "..." の単一行で作り直す。

### 12.3 将来タスク(Phase 3 の残り / 今後)

- **Priority 2: 画像生成(TT/グリッド)の高速化**。1回 20〜35秒かかる。grid 生成の
  `for n in grid_order: db.query(Artist).filter(Artist.name == n).first()` が N+1 で、
  アー写読み込みの個別ラウンドトリップが主因と推定。次の調査対象。`[PERF]` ログは
  Priority 2 でも使うため当面残置。
- **`views/projects.py:71` の削除が services を経由しない孤立経路**(直接 `db.delete`)。
  今回は暫定で `list_projects_for_selector.clear()` のみ追加。将来
  `project_service.delete_project_by_id` 経由に統一する。
- **`flyer_date_format`(`views/flyer.py:351` 付近)が key 無し radio + 外部
  session_state 管理の「動くが美しくない」パターン**。将来 alignment と同様に
  整理候補。
- **services 層が `@st.cache_data` / `@st.cache_resource` 経由で Streamlit に依存**。
  将来の API 化(LINE Bot 前提、セクション 11.3 参照)で services を画面非依存に
  戻す際の対象。
- **`[PERF]` 計測ログ**は Phase 3(Priority 2 含む)完了時に一括 revert 予定。
- **既存 DB のゴミデータ**: `time_alignment_sel` が DB の flyer_json に焼き付いた
  プロジェクト 4 件(`has_sel_key=true`、いずれも値 "center" で無害)は除去 UPDATE
  せず放置。テスト用 id=22/26 等は谷内さん側で手動削除予定。

### 12.4 設計手法の知見(本番のみ環境ゆえの制約と工夫)

- ローカル実行環境なし・DB は本番 Supabase のみ という制約下では、`scratch/repro_flyer.py`
  の「DB 非書き込み純ロジック再現」が唯一の push 前検証手段になる。旧実装と
  新実装の出力を byte-for-byte 比較する assert で「挙動不変」を機械的に証明してから
  push する。
- 本番動作確認は本番ログ(Manage app → Logs)の `[PERF]` 抽出で行う。コミット
  メッセージの「検証済み」は自己申告 → 計測ログの生出力を必ず目視確認してから次に進む。
- 各タスクは 1 コミット = 1 デプロイ = 1 検証のサイクル。「ついでに」の修正は
  別コミットに分離して原因追跡を容易にする。

## 13. Phase 2B-2-b で機能等価から外した 2 点 (2026-06-30)

Phase 2B-2-b (TTエディタ往復を `draft_rows` 一本化) は原則「機能等価リファクタ」
として実装したが、以下 2 点は旧コードの挙動と差分が出る。いずれも旧の potential
bug の修正にあたり「悪い方向への変更ではない」と確認済み。

### 13.1 開演前物販の `goods_start_time` が `open_time` に追従するようになる

**旧経路の挙動 (b829e23)**:
- overview 等で `tt_open_time` が変更され TT タブ render に入ると、
  `if last_open != current_open: rebuild_table_flag = True` で rebuild が trigger。
- rebuild ブロック内で `binding_df` を再構築するが、その時点で
  `tt_pre_goods_settings["GOODS_START_MANUAL"]` は **古い値のまま**。
  → editor 表示は古い値で描画される。
- 同 render の後段 (L484-491) で `tt_pre_goods_settings["GOODS_START_MANUAL"] =
  tt_open_time` で上書きされるが、`rebuild_table_flag` は同 render 内で `False`
  に戻されており、`last_check_key` も更新済み。
- → 次 render 以降は rebuild が走らない → binding_df 再構築されない →
  **editor 表示が古い値のまま固定** される potential bug。

**新経路の挙動 (Phase 2B-2-b)**:
- `_normalize_edited_rows` を editor 戻り直後・`!=` ガード前に通すことで、
  `draft_rows[開演前物販].goods_start_time = open_time` を毎 render で強制上書き。
- 上書きで `draft_rows` が変わると `!=` ガードで `set_draft_rows + mark_dirty`、
  次 rerun で editor が新 `draft_rows` 由来で再描画 → 新値表示。
- → **1 rerun 後に新値表示**。無限ループしない (scratch で
  `probe_open_time_display_lag.py` により検証済み)。

**実害評価**: ユーザー impact 軽微。`tt_open_time` の編集経路は overview のみ
(TT タブ内の selectbox は Phase 2B-1b で削除済み)、overview save 経由で
reload_project が走り `draft_rows` も `tt_pre_goods_settings` も両方再 populate
されるため、本 bug の顕在化経路は「TT タブを開いたまま overview に切り替えて
open_time 変更し TT タブに戻った瞬間」のみ。`mark_dirty` も overview 側で既に
立っているため二重実害なし。

**scratch**: `scratch/probe_open_time_display_lag.py` で旧 vs 新を multi-render
比較し「新経路の表示ラグ ≤ 旧経路」を実証。

### 13.2 CSV 取込で「開演前物販」「終演後物販」名行を skip するガードを追加

**旧経路の挙動 (b829e23)**:
- CSV に `name == "開演前物販"` や `name == "終演後物販"` の行が含まれた場合、
  `tt_artists_order.append(name)` で通常行として 6 状態に取り込む。
- rebuild ループ L425 でも通常行として扱われ、editor 戻り L484-491 の分岐
  (`if name == "開演前物販":` 等) は `tt_pre_goods_settings` 等を更新するが、
  通常行設定 (`tt_artist_settings` / `tt_row_settings`) は別経路で同時に
  追加されている。結果として開演前物販が二重化 or 表示の整合が乱れる可能性が
  あった。

**新経路の挙動 (Phase 2B-2-b commit2 まとまり③ Edit B)**:
- `import_csv_callback` の for ループ冒頭で
  `if name in (PRE_GOODS_ARTIST_NAME, POST_GOODS_ARTIST_NAME): continue` を追加し、
  CSV 内の特殊行名は `new_rows` に取り込まない。
- 開演前物販は既存 `draft_rows` の `existing_pre` を保持する形で温存、
  終演後物販は CSV 内に `IS_POST_GOODS=True` 通常行があれば次 rerun のまとまり②
  集約 trigger で末尾に append される設計と整合。
- → **CSV 由来の特殊行は二重化せず、UI トグル/集約で一元管理される**。

**scratch**: `scratch/probe_csv_special_row_names.py` で 3 シナリオ
(終演後名行のみ / 開演前名行のみ / 両方+IS_POST_GOODS=True 通常行) を実証し、
ガードなしでは開演前物販の二重化が発生 (`len=4, names=[開演前物販, 開演前物販, X, Y]`)、
ガードありでは 1 件のみで安定することを確認。

### 13.3 残置した dead code (-c 以降で cleanup 予定)

機能等価維持のため、Phase 2B-2-b では以下を残置:

- `app.py:47` の `rebuild_table_flag` 初期化 (setdefault)
- `services/legacy_adapter.py:193` の `rebuild_table_flag = True` セット
- `services/session_manager.py:70` `SESSION_PROJECT_KEYS` リストの
  `"rebuild_table_flag"` エントリ
- `views/timetable.py:217-224` の `last_check_key` ブロック全体
  (`rebuild_table_flag = True` 行のみ撤去、ブロック自体は dead 状態で残存)
- `views/timetable.py:322` DB ロード経路の `rebuild_table_flag = True`
  (旧 6 状態 populate との並存安全網として残置)

これらは「`rebuild_table_flag` を読む側」が既に全消滅しているため副作用なし。
Phase 2B-2-c 以降の cleanup で削除予定。

## 14. 撤去作業の標準フロー(Phase 2B-2-d で確立)

1. investigation-first: 撤去前に読み取り専用ゲートで依存を潰す。消す対象を誰が
   read/import しているか grep 0件で確認。関数丸ごと撤去は repo 全体 grep で
   外部参照ゼロ(ImportError 回避)を確認。
2. メモの行番号は信用しない。着手時に grep で実行番号を取り直す。
3. 削除は後ろの行から(上を消しても下の行番号がズレない)。
4. 共用関数は丸ごと消さない。6状態専用ブロックだけ外科 delete、他同期は温存。
5. 適用後は grep(実コード0件) + py_compile(COMPILE_OK) の生出力で確認するまで
   完了宣言しない。参照→足場の順(参照元→専用ヘルパーの順で消す)。
6. 本番のみ環境: 中間状態リスクのある撤去は1コミットで完結させ、全撤去し終える
   まで本番での保存/push/テストをしない。

## 15. Phase 2B-2-d 完了記録(2026-06-30)

✅ フェーズ2B-2-d: 旧6状態(tt_*)+ rebuild_table_flag の完全撤去
(2026-06-30 実施、本番反映済み、commit ac33737、net -290行、4ファイル)
- 書く側①: views/timetable.py DBロード経路の6状態展開 + rebuild_table_flag
- 書く側②: legacy_adapter.py _expand_rows_to_legacy(関数丸ごと)+ 呼び出し + rows
- 読む側③: session_manager.py _rebuild_draft_rows_from_legacy(関数丸ごと)+ 呼び出し
           + 専用ヘルパー _coerce_str/_coerce_int/_coerce_optional_int
- init: app.py の6状態 setdefault + rebuild_table_flag + 未使用 import
        (get_default_row_settings)
- clear: session_manager.py SESSION_PROJECT_KEYS の6状態+flag 要素
- 掃除: stale コメント/docstring を現状に修正
温存: tt_editor_key / request_calc(timetable.py 参照)、tt_draft_authoritative
(sentinel・将来棚卸し候補)、_is_persistable(flyer 処理が使用)。
検証: repo 全体 grep で6状態代入・_expand/_rebuild/_coerce の実コード0件を確認。
本番実機テスト(TT編集→保存→往復 / 新規空表示 / 既存表示 / 開演前物販トグル /
画像生成)すべて合格。draft_rows 一本化が本番で旧経路と同一出力を生成。
→ save chain は draft_rows → DB に完全一本化。Phase 2B 本丸完了。
コミット: 30ee2e0 Add CLAUDE.md operational guard / ac33737 Phase 2B-2-d 本体

## 16. Phase 4-0 完了記録(2026-07-01)

✅ フェーズ4-0: data_json を primary 直読みしていた live reader の移行/撤去
(2026-07-01 実施、本番反映済み、commit 03fcd95 / 0368450)

**背景**: Phase 4 本体(projects_v4.data_json 二重書き込みの停止)の前提作業。
書き込みを止めると stale/空データを出す「data_json を primary で直読みする live 経路」を
先に排除する。investigation-first で repo 全体の data_json 使用を棚卸しして判定した。

**data_json 使用の棚卸し結果(projects_v4)**:
- 書き込み(Phase 4 本体で止める対象・今回は温存): `repositories/project_repo.py` の
  apply_draft 過渡期二重書き込み + `_build_legacy_data_json_from_rows`。
- 読み・安全(rows 優先フォールバック。timetable_rows が無い旧 proj のみ落ちる・温存):
  - `repositories/timetable_repo.load_rows`(正規窓口)
  - `views/grid.py` の `elif proj.data_json`(L122/178)
  - `logic_project.py` load_project_data の else(L157、overview.py:75 から live)
- 読み・live blocker(primary 直読み・フォールバック無し → 今回排除):
  - ① `views/projects.py` 「⏱️ タイムテーブルPDF」ボタン(プロジェクト管理メニュー、live)
  - ② `utils/flyer_helpers.py` の generate_timetable_csv_string
     (flyer.py の ZIP 素材同梱から live)
- 死コード(data_json に触るが到達不能。今回は温存、Phase 4 本体で cleanup 候補):
  - generate_event_summary_text_from_proj(呼び出し元ゼロ)
  - create_project_assets_zip(唯一の呼び出しが projects.py でコメントアウト)
- 対象外(別テーブル flyer_templates.data_json。触ると別機能破壊・保護):
  - views/flyer.py(テンプレ読込/保存)、views/template.py(st.json 表示)

**実装(2 コミット・性質で分離)**:
- 03fcd95 PDF 移行(挙動維持リファクタ): projects.py の
  `pd.DataFrame(json.loads(proj.data_json))` を `draft_rows_to_df(load_rows(db, proj.id))`
  に置換。ガードを `if proj.data_json:` → `tt_rows = load_rows(...); if tt_rows:` に変更。
  未使用化した import json / import pandas as pd を撤去(grep 0件確認後)。
  import io は未使用だが指示により温存(Phase 6 の import 整理候補)。
- 0368450 CSV 撤去(機能削除): flyer.py の呼び出し2行 + import から当該関数のみ除去 →
  参照0件を grep 確認 → flyer_helpers.py の関数定義(27行)を撤去。「参照→足場」順。

**検証**: 両コミット py_compile 通過。grep 生出力で projects.py の data_json/json./pd. 0件、
CSV 関数の定義/参照/"Timetable_Data.csv" 文字列すべて0件を確認。本番実機テスト
(PDF ボタン表示 / 内容一致 / 【核心】TT 編集→保存→PDF 再DL で反映=stale でない /
ZIP に CSV 無し・他ファイル無傷)すべて合格。

→ primary 直読みの live 経路が消滅。data_json 二重書き込みを止めても stale 化する読み手が
残らない状態になり、**Phase 4 本体(data_json 廃止)がアンブロック**。

### 罠22: data_json は projects_v4 と flyer_templates の2テーブルにある同名カラム
database.py で projects_v4(TimetableProject, L74)と flyer_templates(FlyerTemplate,
L134)の両方が data_json カラムを持つ。前者は TT データ、後者はフライヤーのテンプレ
プリセット設定で全くの別機能。`grep -rn data_json` の結果を無差別に消すと
flyer_templates 側(flyer.py のテンプレ読込/保存、template.py の表示)を破壊する。
→ 対処: data_json を触る作業では必ず「どのテーブルの data_json か」を先に判定。
  ORM オブジェクトの型(proj=TimetableProject か target_t/tmpl=FlyerTemplate か)で切り分ける。

### 罠23: 「dead code 疑い」の正体が「生きているが半壊(出力が空)」だったケース
申し送りにあった「CSV export に dead-code 疑い」は、実際は呼び出し経路が live だった。
真因は別で、generate_timetable_csv_string が data_json から読む計算後キー
(START/END/GOODS_START/GOODS_END/GOODS_LOC)を、Phase 2B の二重書き込み
(_build_legacy_data_json_from_rows = to_legacy_dict() の入力キーのみ)が一切書いておらず、
2B 以降に保存した proj では時刻・物販列が既に空欄で出力されていた(=半壊)。
→ 教訓: 「使われていない」という申し送りを鵜呑みにせず grep で呼び出し到達性を確認する。
  reader が期待するスキーマと writer が書くスキーマの不一致は「クラッシュしない静かな
  データ欠落」を生む。撤去/移行の判断前に両スキーマを突き合わせること。

## 17. Phase 4 本体 完了記録(2026-07-01)

✅ フェーズ4 本体: projects_v4.data_json への【書き込み】全廃
(2026-07-01 実施、本番反映済み、commit 34a3f5f / 82199b8 / 33d32f3)

**背景**: Phase 4-0 で primary 直読み reader を排除済み。本体では data_json を「書く側」を
全て止め、data_json を読み込みフォールバック専用の過去互換層にする。

**実装(3 コミット・性質で分離)**:
- 34a3f5f apply_draft の data_json 二重書き込み停止 + _build_legacy_data_json_from_rows 撤去
  (project_repo.py -41)。apply_draft の if rows is not None: proj.data_json = ... ブロックを
  丸ごと撤去。唯一の呼び出しが消えた _build_legacy_data_json_from_rows も同コミットで撤去
  (参照→足場)。apply_draft の rows 引数は本体未使用化したが呼び出し側互換のため温存。
- 82199b8 duplicate_project の data_json コピー撤去 (project_repo.py -1)。
  data_json=src.data_json の1行のみ削除。複製先の行データは copy_rows(load_rows→save_rows)
  が timetable_rows にコピーするため、data_json=None でも load_rows は rows を読む → 欠落なし。
- 33d32f3 死コード2関数撤去 (projects.py / utils/__init__.py / flyer_helpers.py)。
  generate_event_summary_text_from_proj(呼び出し元ゼロ)、create_project_assets_zip
  (import+コメントのみ)を「参照→足場」順で撤去。ZIP 残骸コメント3行もクリーンに削除
  (可逆性は Git 履歴が担保。死んだコメントは残さない方針)。

**検証**: 3コミット py_compile 通過。grep 生出力で _build_legacy... /
generate_event_summary_text_from_proj / create_project_assets_zip すべて0件、
project_repo.py の data_json 書き込みが apply_draft・duplicate_project とも消滅を確認。
本番実機テスト(保存→再表示で最新反映 / 新規保存 / 複製 / 各タブ表示 / 告知テキスト)全合格。

→ data_json は「読み込みフォールバック専用」の純粋な過去互換層になり、書き手はゼロ。
  読み(load_rows / load_project_data else / grid.py elif)は温存。旧プロジェクトは data_json
  fallback で読み続けられ、一度保存すれば timetable_rows に移行する。

**同時に修正した stale docstring**: apply_draft / update_project_from_draft の docstring が
「rows を渡すと data_json も同時書き出しする」と撤去済みの挙動を記述し続けていた(罠24)。
別コミット(6073f81)で現状に合わせて修正。

**Phase 6 に送った申し送り(今回は温存)**:
- 未使用 import: project_repo.py の PRE_GOODS/POST_GOODS_ARTIST_NAME、flyer_helpers.py の
  json / pandas / build_event_summary_text、projects.py の io(撤去で芋づる式に未使用化)。
- data_json カラム自体の廃止(スキーマ変更)と load_rows フォールバック撤去は、旧プロジェクトが
  全て timetable_rows に移行し切ったと確認できるまで保留。

### 罠24: 挙動を変える撤去で docstring/コメントが「嘘」に化ける(stale 化)
関数の挙動を変える撤去をすると、その挙動を説明していた docstring/コメントが実態と食い違う。
今回 apply_draft の data_json 書き出しを撤去したが、docstring は「rows を渡すと data_json も
同時書き出しする」と嘘を言い続けていた。放置すると次に読む人が「まだ書いている」と誤解する。
→ 対処: コード撤去と docstring/コメント修正はコミットを分けるのが原則(1コミット=1目的)だが、
  分けたなら必ず申し送りに残し放置しない。撤去の最後に「この撤去で嘘になった記述」を
  撤去した機能名・カラム名で grep(単語ではなく現在形の主張句で)洗い出す。

## 18. Phase 6 一部: 死コード掃除(sentinel 撤去・未使用 import 整理)(2026-07-01)

✅ Phase 6(仕上げ)の一部を先行実施。本番反映済み。
※ 用語注記: 実装中は "Phase 5/Phase 6" と呼んでいたが、正式なフェーズ計画では
  フェーズ5=残りビュー(grid/flyer/artist)移行、フェーズ6=仕上げ。
  今回の sentinel 撤去・import 掃除はいずれもフェーズ6(仕上げ)の一部。

**背景**: Phase 4 / Phase 4-0 で data_json 書き込みを全廃した結果、
それを使っていた関数・定数・sentinel が芋づる式に死コード化した。これを掃除。

**実施内容(4コミット)**:
- b0ac78a sentinel tt_draft_authoritative 撤去。
  read-only 調査で「set/コメント/clearリスト要素のみ、read は0件」の write-only
  死状態と確定(唯一の読み手 _rebuild_draft_rows_from_legacy は 2B-2-d で撤去済み)。
  timetable.py の書き込み2箇所+コメント3行、session_manager.py の clear リスト要素+
  コメント3行を撤去。挙動変化ゼロ。import は巻き込まず。
- 5ab4fa2 未使用 import 掃除(4ファイル)。Phase 4/sentinel 撤去で未使用化した:
  project_repo.py の PRE_GOODS_ARTIST_NAME/POST_GOODS_ARTIST_NAME、
  flyer_helpers.py の json/pandas/build_event_summary_text(+get_day_of_week_jp/
  get_circled_number)、projects.py の io、timetable.py の load_timetable_rows。
  ※ timetable.py の load_timetable_rows は import 行のみ撤去。関数定義と
    logic_project 内の呼び出し(複製経路)は生きているので温存。
  ※ flyer_helpers.py の import io は使用中なので温存(projects.py の io とは別)。
- a8894e6 stale コメント修正。5ab4fa2 で text_generator import を撤去した結果、
  flyer_helpers.py 末尾のコメントが「インポートして使用」と嘘になった(罠24)。
  注釈対象が存在しない孤立コメントのため削除。

**検証**: 全コミット py_compile 通過、各撤去対象 grep 0件、diff はロジック変更ゼロ。
本番実機テスト(TT表示/編集保存/CSV反映/プロジェクト切替、各タブ表示)すべて合格。

**教訓の再確認(罠24)**: 撤去が挙動を変えると、その挙動を説明していたコメントが
嘘に化ける。撤去した機能名で grep して stale コメントを洗い出すこと。
また「複数 import の一部だけ未使用」「同名だが別ファイルでは使用中(io)」
「import は未使用だが関数本体は他所で生存(load_timetable_rows)」のように、
撤去の線引きは grep で1つずつ確定する。

**申し送り(残タスク)**:
- data_json カラム自体の廃止(スキーマ変更)は、旧プロジェクトが全て timetable_rows に
  移行し切ったか SELECT で確認してから。慎重案件。
- Phase 6 の残り: 型ヒント追加、キャッシュ最適化、except: pass 撲滅、
  罠7(毎レンダ ALTER TABLE)の撤去。
- Phase 5(残りビュー grid/flyer/artist 移行)は未着手。
  (※ その後 2026-07-06 に artist を完了。最新の現在地は §19 末尾を参照)

## 19. Phase 5: artists ドメイン完了(2026-07-06)

✅ `views/artists.py` の DB 直アクセスを完全排除。本番反映済み(origin/main = `e7c9f01`)。
これで **artists ビューの `db.query` は 0 件 =「view から ORM 全滅」達成**。

**コミット構成(3 段)**:
- **①〜C7(9 コミット、`7643335`〜`1564187`)**: artist ORM 直操作を
  `repositories/artist_repo`(単機能・commit しない)+ `services/artist_service`
  (session と commit/rollback を所有)経由へ一本化。read は frozen dataclass
  `ArtistView` で返し ORM を view に渡さない。
- **表示修正 `be10555`**: create/restore/exists のメッセージが即 rerun で消える問題を修正
  (罠25)。
- **⑤-a(D1〜D4、`838d7dc`〜`e7c9f01`)**: 最後に残った merge(名寄せ)経路を service 化。
  - D1 `838d7dc`: `artist_repo.reassign_timetable_rows` 実装(スタブ脱却)。完全一致(`==`)・
    全プロジェクト横断・`artist_name` 列のみ更新・commit しない。
  - D2 `ffb007d`: `artist_service.merge_artists` 新設。1 トランザクション合成
    (reassign → loser を `_merged_{ts}` にリネーム → soft_delete → commit、順序厳守=
    付け替えは rename 前の loser 名で)。戻り値 `(count, status)`,
    status ∈ {merged, not_found, error}。`_merged_` は delete の `_del_` とは別物のため
    `service.soft_delete_artist` は使わず repo 単機能を合成。
  - D3 `bc947d3`: view の merge ブロックを service 呼び出し+status 分岐に置換。
    `winner==loser` ガードは view 据え置き。
  - D4 `e7c9f01`: 未使用 import 撤去(`Artist` / `TimetableRow` / `upload_image_to_supabase`)。

**成果(3 層構成の確立)**:
- **artist_repo**: 書くだけ・単機能・commit しない。
- **artist_service**: session の生成/クローズと commit/rollback 境界を所有。
- **view**: service を呼ぶだけ。ORM(`db.query`)・commit/rollback を持たない。

**①成果物からの変更 2 件(明記)**:
1. **C1**: `artist_repo` に `update_artist` を追加(①の初期シグネチャに無かった。
   名前/画像更新の共通経路として必要)。
2. **C1.5**: `ArtistView` に `is_deleted` を追加(create-or-restore 判定に必要。
   同名の削除済みが居れば復元、居なければ新規、を service で分岐するため)。

**意図的差分(1 点)**: エラー時メッセージの汎用化。旧 view は
`st.error(f"統合エラー: {e}")` と例外オブジェクトを画面表示していたが、新実装は例外を
service の `logger.error(..., exc_info=True)` に記録し、view は汎用文言を表示する
(create 移行の前例に倣う)。異常系のみの差で正常系は bit-parity。

**B' 方式の教訓(read/write の再シーケンス)**:
artists は read の ORM(`db.query(Artist)` の結果オブジェクト)が write に流れ込む結合が
あった。そこで **write を先に id ベースで service 化 → 最後に read を一本化** する順で
進めたのが有効だった。副産物として、下流(write 側)が先に id ベース化されていたため
**C7(一覧 read の一本化)が 1 行置換で済んだ**。read を先に触ると write 側の ORM 依存が
宙に浮くが、write を先に固めると read の切り替えが最小差分になる。

### 罠25: `st.success`/`st.error` の直後に `st.rerun()` を置くとメッセージが消える
メッセージが描画される前に再実行が走り、ユーザーはトースト/エラーを目視できない。
- **成功系(DB 変更あり)**: `st.success/st.toast` → `time.sleep(1)` を挟んでから `st.rerun()`
  (描画時間を確保してから再実行)。
- **エラー系(DB 変更なし)**: `st.rerun()` しない(そのまま留まってメッセージを見せる)。
※ 旧来から存在した挙動で Phase 5 の回帰ではない。`be10555` で修正済み。

### 罠26: アーティスト merge は `TimetableRow.artist_name` しか付け替えない
名寄せ(merge)は `timetable_rows.artist_name` のみ winner 名に書き換える。しかし
アーティスト名を文字列で持つ箇所は他にもあり、loser 名が残留する:
- `projects_v4.grid_order_json`(`{"order":[アーティスト名,…]}`)
- 旧 `projects_v4.data_json`(`ARTIST` フィールド・読み込みフォールバック)
→ グリッド/フライヤーの並び順で loser 名が参照され、該当アーティストの表示落ち・
  名前不一致リスク。
**【⑤-b 追記 2026-07-06】`grid_order_json` は対応済み**(§21)。merge 時に
`project_repo.reassign_grid_orders` が order 内の loser 名を winner 名へ名寄せする
(dict の他キー温存 / 裸 list は裸 list のまま)。`data_json` の旧名は既知の制限として
非対応(§21 参照)。

### 罠27(対策パターン): Edit ツールの大ブロック置換は byte-exact マッチで通す
Edit で複数行ブロックを置換する前に、対象範囲の**実バイト(空行の trailing 空白を含む)**を
`sed -n 'A,Bp' file | cat -ve` 等で確認し、`old_string` を byte-exact に一致させると
置換失敗を防げる(⑤-a D3 で実証。空行に 20/28 スペースの trailing があった)。
逆に、**インデント変更を伴う構造撤去(try/finally 外し等)は Edit ツールで行わない**
(大規模再インデントは罠19/20 の破損を招く)。⑤-a では未使用 DB セッションの撤去を
この理由で見送り、⑤-b に申し送った。

### 罠28(運用): ツール呼び出しが XML 生テキスト化(パースエラー)したときの復帰
Claude Code のツール呼び出しが XML 生テキストとして出力され失敗することがある
(長時間セッションで発生しやすい)。対処:「もう一度〜からやり直して」で復帰を試み、
再発するならセッションを仕切り直す。**成果はコミット済みなら無傷**なので、こまめな
コミットが保険になる。

## 20. 運用メモ: リモート運用(claude remote-control / spawn mode)

Mac で `claude remote-control`(スタンドアロン・spawn mode)を常駐させると、
スマホの Code タブから**新規ローカルセッションを作成**できる。
- **spawn mode は same-dir を選択**(1 ブランチを積み上げる運用と整合。worktree は不採用)。
- スマホからの新規セッション作成には **GitHub 連携(コネクタ)の認可が必要**。
- **Mac のスリープで切れる**ため、外出前はスリープ設定に注意(電源接続+スリープ抑止)。

---

## 21. Phase 5-⑤-b: merge の grid_order_json 名寄せ + 未使用セッション撤去(2026-07-06)

✅ merge(名寄せ)の挙動改善(grid_order_json の付け替え)と、⑤-a 申し送りの
未使用 DB セッション撤去を実施(branch: refactor/phase-5b-grid-order)。

**コミット構成**:
- **E1 `4673f6a`**: `project_repo.reassign_grid_orders` 新設。全プロジェクトの
  `grid_order_json` 内 `order` リストの loser 名を処理(winner 既在 → loser 削除で重複回避 /
  不在 → 位置維持で置換)。純ロジックを DB 非依存の `_reassign_grid_json` に切り出し
  (scratch で実コードを 9 群検証)、`reassign_grid_orders` は薄いラッパ(commit しない)。
- **E2 `2516d95`**: `artist_service.merge_artists` を拡張。TT 付け替えの直後(rename 前・
  同一トランザクション)に grid 名寄せを追加。戻り値を `(rows_count, grid_count, status)` の
  3-tuple 化。toast を「TT N 箇所 / グリッド並び順 M プロジェクトを修正」に更新。
- **E3 `3bf0e95`**: `views/artists.py` の未使用 DB セッション撤去(下記 罠29)。
- **E4**(本追記): 知見ドキュメント更新。

**設計判断(合意済み)**:
- `grid_order_json` は dict 形式(`{"order":[...], row_counts/alignment/... }`)と旧来の
  裸 list 形式の両方がありうる。**読み込んだ形状のまま書き戻す**(dict は order 以外の
  キーを温存、裸 list は裸 list のまま)。`_parse_json` は list を dict に正規化して形状を
  潰すため使わず、`json.loads` 直+自前 `try/except json.JSONDecodeError` にした。
- 照合は完全一致(`==`)。`reassign_timetable_rows` と同一意味論(前後空白は正規化しない)。
- `reassign_grid_orders` は `grid_order_json` への「apply_draft に次ぐ 2 人目の書き手」。
  dict の order 以外キーが保存前後で不変であることを scratch テストで担保。

**既知の制限(意図的に非対応・合意済み)**:
- **旧 `data_json` の `ARTIST` 名**: Phase 4 で確立した「data_json は書き手ゼロ」不変条件を
  守るため触らない。未移行の旧プロジェクトは一度保存すれば `timetable_rows` に移行し解消。
- **loser の Storage 画像(image_filename)**: 孤児化は現行仕様。削除は破壊的操作のため非対応。
- **過去の merge で既に残留した `grid_order_json` の旧名**: 今回の対応は「今後の merge のみ」。
  既存残留分の一括修復はデータ移行の慎重案件として申し送り(SELECT で影響範囲を確認して
  から別途判断。今回は実施しない)。

### 罠29(対策パターン): 構造的 dedent は `git diff -w` だけでは証明できない — AST 文字列比較で塞ぐ
未使用 DB セッション撤去(`try/finally` 外し+本体 1 段 dedent)を Edit ツールではなく
scratch の python スクリプトで機械実行した(罠27:インデント変更を伴う構造撤去は Edit 不可)。
このとき **`git diff -w`(空白無視)は「削除された当該行のみ」を示せるが、それだけでは
不十分**: try 本体に複数行文字列(`st.info("""...""")`)があると、その内部行も dedent されて
**表示テキスト(文字列の中身)が変わる**。空白変更なので `git diff -w` は検出できない(機械証明の穴)。
- **対策**: dedent 前後で `ast.parse` し、全文字列定数(`ast.Constant` かつ `isinstance(v, str)`)を
  多重集合として抽出して完全一致を assert する(`scratch/verify_artists_strings.py`)。
- **dedent 側のガード**: `ast` で複数行文字列の内部行(`lineno+1 .. end_lineno`)を保護集合に集め、
  その行は dedent 対象から除外する。開始行(`lineno`= コード行)のみ dedent する。
- ⑤-b E3 では、ガード無し版を一度実行して AST 比較が不一致を**実際に検出**することを確認して
  から(検証が no-op でない証明)、ガードを追加し MATCH を得た。

## 22. ホットフィックス: グリッド「各行の枚数設定」が他プロジェクト値で汚染される(2026-07-06)

✅ 罠3(プロジェクト切替で古い widget 内部状態が残る)の実例。止血のみ実施
(branch: fix/grid-row-counts-residue、コミット `7379418`)。根治は grid ビュー移行時。

**症状**: グリッドの「各行の枚数設定(カンマ区切り)」で保存した値(例 `5,5,5,6,6`)が、
後日プロジェクトを開くと `5,5,5,5,5` のように全行同数へ化ける。再現は「時々」で ⑤ 以前から。

**原因(調査で確定)**:
- `views/grid.py:223-229` の text_input は `key="grid_row_counts_input_widget"`(固定 key)と
  `value=st.session_state.grid_row_counts_str` を併用(罠18 構造)。Streamlit は key が
  session_state に既存なら `value=` を無視し key の値を採用する。
- この widget key は `SESSION_PROJECT_KEYS` にも `clear_project_session()` の dynamic_prefixes
  にも該当せず、**プロジェクト切替で消えずに残留**。前プロジェクトの枚数設定が入力欄に居座る。
- reload(`legacy_adapter.py:79` が `grid_order_json.row_counts_str` から正しい値を復元)しても、
  `grid.py:229` が `grid_row_counts_str = row_counts_input`(= 残留 widget 値)で**上書き**。
- 保存(`sync_session_to_draft` が `grid_row_counts_str` を拾う)で grid_order_json に**焼き付き恒久破壊**。
- 直前に既定 `5,5,5,5,5` のプロジェクトを見ていると、次に開いた `5,5,5,6,6` の欄が
  `5,5,5,5,5` を表示 → 保存で `6,6` が消える。「時々」= 直前に何を開いたかに依存。

**止血(F1)**: `grid_row_counts_input_widget` を `SESSION_PROJECT_KEYS` に追加し、切替時に消す。
以後 reload 後は text_input が `value=` の正しい値を採用する。

**申し送り(grid ビュー移行時の根治)**:
- widget key の SSOT 一本化(罠18 パターン): `value=` + 外部 session_state 書き込みの併用を廃し、
  真の SSOT 1 本にする。固定 key は project_id 込みにするか draft 直結にする。
- `grid.py:145` の settings_json 旧読み経路の撤去(保存キー `row_counts_str` と読みキー
  `row_counts` の不一致を内包。新形式では `if grid_conf:` で skip されるが旧データで発火しうる)。
- `grid.py:212-221` の「空文字/パース不能 → `[5]*new_rows` = 全行 5」pad の防御見直し。
- **既に壊れたデータは自動修復不可**(正しい元値が DB に残っていない)。気づいたときに
  手入力で再保存して回復する運用。

## 23. テスト自動化基盤(AppTest スモークテスト)(2026-07-06)

✅ ヘッドレスの自動スモークテスト基盤を導入(branch: feat/apptest-smoke、
コミット `db94f84`、**本番コード変更なし**)。read-only DB 接続で本番データを保護。

### 23.1 概要
- `streamlit.testing.v1.AppTest` によるヘッドレステスト。`tests/` に配置。
- スモーク2本:
  - `test_smoke_all_tabs`: 既存プロジェクトを1件選択し、workspace の全4タブ
    (概要/TT/グリッド/フライヤー)が例外ゼロで描画される(`at.exception` が空)。
  - `test_no_value_bleed_on_switch`: row_counts の異なる既存プロジェクト2件を
    交互選択し、grid の枚数設定が混入しない(ホットフィックス `7379418` / §22 の回帰テスト)。

### 23.2 安全設計(read-only 方式)
- 本番 Supabase に**読み取り専用ユーザー `event_app_readonly`** を新設(SELECT のみ GRANT。
  谷内さんが SQL Editor で作成)。
- テスト用 secrets は `.streamlit/secrets.readonly.toml`(**gitignore 済**・谷内さん手動配置)。
  雛形は同名 `.example`(ダミー値・コミット済)。DB_URL のユーザーを event_app_readonly にする。
- **★安全弁**: `tests/conftest.py` の fixture が `SELECT current_user` を実行し、
  `event_app_readonly` 以外なら `pytest.exit` で**全テスト即中断**。誤って書き込み可能
  ユーザーで走らせない物理ガード。psycopg2 未導入時に接続不可→即中断する fail-safe も実地確認済み。
- テスト操作は SELECT のみ(選択・描画)。保存・新規作成・削除は行わない
  (read-only ユーザーで物理的にも不可)。

### 23.3 技術上の注意(将来の保守者向け)
- **この Streamlit(1.50.0)の AppTest には secrets 注入口(`at.secrets`)が無い**。代替として
  `streamlit.runtime.secrets.secrets_singleton._secrets` へ read-only 値を**直接注入**する方式を採用
  (`config.get_option("secrets.files")` 経路をバイパスし、本番 `secrets.toml` を一切参照させない)。
  **★内部 API 依存**: Streamlit バージョン更新時は要再確認(将来 `at.secrets` が入れば正攻法へ移行)。
- **engine は import 時に1回生成**されるため、同一プロセスで複数 DB_URL の切り替えは不可。
  read-only 単一 URL なら問題なし。将来 write テストを足すなら別プロセス化か engine の DI 化が必要。
- **`st.tabs` の中身は AppTest で全てツリーに載る**ため、タブ切替操作なしで全タブの widget を
  検査できる(罠16 の eager 評価がテストでは好都合)。

### 23.4 実行手順(`tests/README.md` 参照)
```
python3 -m pip install -r requirements-dev.txt
python3 -m pytest tests/test_smoke_apptest.py -v --disable-warnings
```
前提: `.streamlit/secrets.readonly.toml` の配置(gitignore 済のため clone しても付いてこない)。
DB ドライバ `psycopg2-binary` が必要(本番 requirements.txt にも記載)。

### 23.5 限界と展望
- read-only のため**保存フロー(write 経路)は自動テスト不可** → 手動テストを継続。
- grid / flyer ビュー移行時の回帰検知の土台(特に §22 の grid 根治時に有効)。
- CI(GitHub Actions)化は将来オプション(read-only secrets の注入設計が必要)。

---

## 24. Phase 5 grid スライスA: N+1 撤去(バッチ read 窓口の新設)(2026-07-07)

✅ grid 生成の N+1(名前ごとに `db.query(Artist)`)を1クエリのバッチ read に解消。
本番反映済み(origin/main = `bd50055`、実機テスト合格)。branch: refactor/phase-5-grid-n1。

**背景**: Phase 5 grid ビュー移行の第一スライス。全体 Phase 0 調査で
grid.py は write ゼロ・read した Artist ORM の下流は画像生成(logic_grid)のみと確定
(B' 再シーケンス不要=artists の merge と違い read ORM→write の結合が無い)。この N+1 を
artist_repo/service にバッチ read 窓口を新設し ArtistView のリストで返すことで解消した。
ArtistView 返却で logic_grid が(生き経路で)ORM 非依存になり、将来の API 化
(services を画面非依存に戻す件、§11.3)の布石も兼ねる。

**コミット構成(2段)**:
- **`714c091`**: `artist_repo.get_artists_by_names(db, names) -> list[ArtistView]` +
  `artist_service.get_artists_by_names(names)` を新設(この時点では誰も呼ばない=inert)。
  1クエリ `filter(Artist.name.in_(unique_names)).order_by(Artist.id).all()`、
  `{name: ArtistView}` マップを「未登録 name のみ格納」で構築(id 昇順の先頭採用)、
  入力 names を順走査して `[by_name[n] for n in names if n in by_name]` で返す。
  repo は commit しない・db 受け取るだけ、service は SessionLocal open→try→finally close。
- **`bd50055`**: grid.py の N+1 ループ(旧 L329-332:`target_artists=[]` + `for n: first(); if a: append`)を
  `target_artists = artist_service.get_artists_by_names(st.session_state.grid_order)` 1行に置換。
  `Artist` import 撤去(grid.py 内の唯一の参照が消えたため)、`artist_service` import 追加。

**bit-parity の意味論(Phase 0 で確定)**:
- 順序保持・重複保持・見つからない name は skip(旧 `if a:` と同値)。
- is_deleted フィルタは付けない。削除/merge 済みは name が `_del_`/`_merged_` に改名済み(罠26/§19/§21)
  のため素の name には一致せず、実質 active のみ拾う=旧クエリの非フィルタ挙動を踏襲。
- タイブレーク: 旧 `.first()` は order_by 無し(DB依存)。新窓口は `order_by(Artist.id)` で
  PK 昇順の先頭1件を明示採用。正常系(同名 active 1件。create-or-restore ガードで担保)は出力不変、
  複数時のみ決定論的になる「旧より厳密」な意図的差分。
- crop_*: `_to_view` が `(x or default)` で写し、logic_grid の `(getattr or default)` と二重でも
  冪等・同値(touched 6属性 {id,name,image_filename,crop_scale,crop_x,crop_y} ⊆ ArtistView)。

**検証**: repo/service py_compile COMPILE_OK。純ロジック5ケース(全ヒット/一部missing/入力重複/
同名active2件/空入力)を旧ループ相当と name 列で一致 assert(scratch、DB非書き込み・§12.4 方式)。
grid.py の `db.query(Artist)` / `Artist` 参照ともに grep 0件。logic_grid.py・
`generate_grid_image_buffer`(dead code)は無変更。実機テスト(既存グリッド生成が
見た目完全一致=crop 込み / 存在しない名前で枠抜け・クラッシュなし / 2件切替で混ざらない)合格。

**申し送り(grid 残スライス)**:
- **row_counts SSOT 根治(§22)**: 5015c17 は止血のみ。罠18 の value=/外部書き込み併用の廃止、
  settings_json 旧読み L145(キー row_counts vs row_counts_str 不一致)の撤去、
  pad(空文字→全行5)の防御見直し。grid 残スライスで実データ破壊リスクを持つのはここだけ。
- **project/rows read の service 化**(grid.py L72/103/110/165)、**フォント read の service 化**
  (L35/49・他ビュー共用の可能性あり要影響範囲確認)。この2つを潰すと grid の db.query 全滅が完成。
- `generate_grid_image_buffer`(grid.py・呼び出し実体ゼロの dead code)は今回ノータッチ。
  将来復活時は ArtistView 前提になる。

---

## 25. Phase 5 grid: row_counts SSOT 根治(§22 の恒久修正)(2026-07-07)

✅ grid の「各行の枚数設定」がプロジェクト切替後に他プロジェクト値/default で汚染され、
保存で grid_order_json に恒久破壊される問題(§22・罠3/罠18)を根治。本番反映済み
(origin/main = `ebbd39d`、実機テスト全項目合格)。branch: refactor/phase-5-grid-rowcounts-ssot。
5015c17(§22)は止血のみだったが、本作業で汚染源を2つとも撤去し構造的に根絶した。

**Phase 0 で確定した汚染機序(3ステップ)**:
① overview で project 選択 → `load_project_data`(logic_project:161)が正しい row_counts を復元。
② grid タブ遷移 → `grid_settings_loaded` 未設定 → grid.py の settings_json 旧読みブロックが
   **間違ったカラム(settings_json)/間違ったキー(row_counts)** で正しい値を default "5,5,5,5,5" に上書き。
③ pad(session書き戻し)→ widget 手動書き戻し(罠18)→ 保存で grid_order_json に焼き付き恒久破壊。
   `grid_settings_loaded` は切替時に clear されるため、②は proj 切替のたびに再発火(§22 の残留性の正体)。

**復元経路のキー整合性(Phase 0 調査結果)**:
- ✅ `load_project_data`(logic_project:161)← grid_order_json / `row_counts_str`(正)
- ✅ `sync_draft_to_legacy_session`(legacy_adapter:79、reload_project 経由)← grid_order_json / `row_counts_str`(正)
- ❌ grid.py 旧読みブロック ← settings_json / `row_counts`(唯一の汚染源。撤去対象)
- 保存も `_GRID_KEY_MAP`(session_manager:174)で session `grid_row_counts_str` → draft `row_counts_str` と対称。

**コミット構成(2段)**:
- **`d8dbc4c`(commit1)**: settings_json 旧読みブロック(grid.py L136-153)を丸ごと撤去。
  道連れフラグ `grid_settings_loaded` / `current_proj_id_check`(旧読み専用と grep 確認)と
  SESSION_PROJECT_KEYS の該当2エントリも撤去。純撤去 -22行、挙動変化なし(死経路)。
  **read-only SELECT で撤去安全性を本番確認**: grid_order_json が空で settings_json にしか
  grid データが無い「超旧 project」= 0件、settings_json に grid_settings を持つ project = 0件
  (§23 の event_app_readonly 経由・SELECT のみ)。→ この旧読みは書き手不在の完全な死経路と確定。
- **`ebbd39d`(commit2)**: 罠18 を構造的に根絶(方針B)。
  - widget を `key="grid_row_counts_str"`(真の SSOT)に直バインド。value=・手動書き戻し(旧L205/L209)を撤去。
  - pad(旧L189-201)の session 書き戻しを撤去し、行数(new_rows)に合わせた長さ整形
    (不足→5補完/過剰→切落し)を**生成直前の parsed_counts 作成箇所へ移設**。ローカル変数で整形し
    SSOT には焼き戻さない。→ widget 描画後に SSOT へ外部 write する経路がゼロ = 真の SSOT 一本化。
  - 5015c17 の止血エントリ(SESSION_PROJECT_KEYS の grid_row_counts_input_widget)を撤去。
  - スモークテスト(test_smoke_apptest.py)の ROW_COUNTS_WIDGET_KEY を新 key に更新(下記)。

**方針B の意図的な UX 変更(合意済み)**:
grid_rows(行数)を変えても枚数欄の表示テキストは自動追従しなくなる(pad が session を書かないため)。
ただし生成時に行数へ整形するので、**生成される画像の行数・枚数は従来どおり正しい**。表示だけの差。

**スモークテストの前倒し統合(commit2 に含めた判断)**:
widget key 変更で test_smoke_all_tabs と test_no_value_bleed_on_switch が旧 key 直参照で赤化(KeyError)。
commit2 単体では**回帰網が一時無効**になり本番 merge のリスクになるため、テスト修正を commit2 に前倒し
(回帰網を割らない原則)。修正は ROW_COUNTS_WIDGET_KEY 定数の1行更新のみ。**アサーション本体は変更せず**、
「切替で row_counts が混ざらない(§22 の不変条件)」が直バインド構造でも維持されることを緑で実証
(テスト意図を弱めない形で緑化)。当初想定の commit3 は消滅し、全体は2コミット構成に。

**検証**: 各コミット py_compile COMPILE_OK、grep で旧 key/旧読み経路の実コード0件、スモーク緑(2 passed)。
実機テスト(①切替でリロードせず正しい枚数表示=表示ラグ解消 / ②編集保存往復で焼き付き破壊なし /
③reset が直バインド後も有効 / ④行数変更で表示は伸びないが生成は正しい)すべて合格。

**申し送り(grid 残スライス)**:
- **project/rows read の service 化**(grid.py L72/103/110/165)、**フォント read の service 化**(L35/49)。
  この2つを潰すと grid ビューの `db.query` 全滅が完成(row_counts のような実データ破壊リスクはなく、
  純粋な read 移行。artists の型を横展開できる)。

### 罠30(対策パターン): 「リロードで直る」表示バグは DB でなく widget/session の残留を疑う
「保存値は正しい(リロードすると正しく出る)が、開いた直後は前の値が出る」症状は、DB 破壊ではなく
表示レイヤー(罠18 の widget 固定 key 残留、罠3 のプロジェクト切替残留)が原因のことが多い。
→ 対処: まず「リロードで直るか(=DB は無事か)」を切り分ける。直るなら緊急 revert 不要、widget/session の
SSOT 一本化で根治する。慌てて revert せず、汚染源を1つずつ潰す。

### 罠31(調査手法): 撤去の安全性は read-only SELECT で本番実データを確認してから確定する
「この旧読み経路を撤去して大丈夫か(=撤去するとデータ復元不能になる project が居ないか)」は、
コード読解だけでは確定できない。§23 の read-only ユーザー(event_app_readonly)+ セッション readonly 固定で
本番 DB に SELECT を流し、影響 project 数を実測してから撤去判断する(本番データ保護モードに抵触しない)。
今回「grid_order_json 空 かつ settings_json に grid データを持つ超旧 project = 0件」を確認して
丸ごと撤去に踏み切れた。

---

## 26. Phase 5 grid スライスB1: rows read の service 化(data_json 直読み崩し)(2026-07-08)

✅ grid.py の TimetableRow read(DB rows 経路 + data_json インライン経路の二重実装)を
timetable_service.get_rows_for_project → load_rows の1本に一元化。本番反映済み
(origin/main = 6e5ac5d、実機テスト全項目合格)。main 直コミット。

**コミット構成(2段)**:
- f138e92(コミット1・inert): services/timetable_service.py 新設。
  get_rows_for_project(project_id) -> List[TimetableRowDraft] が SessionLocal を
  open→try→finally close で所有し、内部で timetable_repo.load_rows(db, id) を返す
  (artist_service と同一の session 所有パターン、repo は無変更・commit しない)。inert(誰も呼ばない)。
- 6e5ac5d(コミット2・置換): grid.py のメイン経路・reset 経路とも rows 取得を
  get_rows_for_project 1呼び出しに一元化。data_json インライン読み(旧 L122-132 / L158-172)、
  reset の temp_db=next(get_db()) と finally close、L103 の if proj:(+ proj.data_json 判定)を撤去。
  未使用化した import json / TimetableRow を撤去。純減 -37行。

**退化防止の要点(合意済み設計)**: load_rows は hidden/物販/転換/調整 をフィルタせず reverse/dedup も
しない。よって「生の行取得だけ load_rows に一元化し、grid 側のフィルタ変換
(物販/終演後物販/転換/調整 除外・is_hidden skip・strip・空 skip・reverse+dedup)は DTO
(draft.artist_name / draft.is_hidden)の上にそのまま残す」統合に限定。フィルタを落とすと
hidden/物販 混入の退化になるため、フィルタ loop は DTO 側へ移設して維持。

**検証(§12.4 方式・DB 非書き込み)**: scratch/verify_grid_order_parity.py で grid_order 生成の
新旧 byte パリティを機械証明。(1)-(8) ALL PASS。本命 (7)(8)= data_json を DTO 化する from_dict の
抽出(IS_HIDDEN の 1/0/None/欠落 の bool 化、ARTIST の欠落/空/前後空白の _to_str+strip)が
旧インライン抽出と完全一致=罠23(reader/writer スキーマ不一致による静かなデータ欠落)クリア証明。
併せて各 Edit を diff -w + grep(撤去シンボル0件 / セレクタ・Font・L62 db 温存)で証明、
py_compile COMPILE_OK。scratch は未 commit(検証手段のため履歴に残さず手元温存)。

**意図的差分3点(退行ではなく整理/頑健化)**:
1. reset の toast を「JSONから構成を読み込みました」→「タイムテーブルから最新の構成を
   読み込みました」に統一(load_rows 一元化で source 区別不可、実データ・grid_order 非影響)。
2. data_json 非 dict 混入時、旧インラインは AttributeError→grid_order 空 / 新は isinstance skip で
   頑健継続。実データ上 data_json を通すのは load_rows フォールバックのみ(G2)で影響なし。
3. L103 if proj: 撤去→load_rows 空判定で代替。旧 reset の elif ....first().data_json: は
   削除済み project で .first()==None→AttributeError で落ちていたが、新は空返しで no-op=クラッシュ解消(頑健化)。

**申し送り(既知の潜在事項・B1 非対応)**: セレクタ/service の sort キー
(x.event_date or "0000-00-00", reverse=True)は日付あり(date)と日付なし(文字列)混在で
date と str 比較 TypeError の潜在リスク。grid・service 双方同一挙動のため B1 では触らず、
B2 でも悪化しない既知事項として記録。

**grid 残スライス**:
- B2: セレクタ(L72 db.query(TimetableProject).all())を list_projects_for_selector へ。
  Phase 0(G5)完了済み=日付ありは完全一致、差は日付なしラベル "None …"→"---- …" のみ(改善方向)、
  id 逆引きはタプルで無改造代替可。
- スライスC: Font read(L35/49 の Asset/AssetFile、L217/289 等の font helper)+ L62 db=next(get_db())
  の最終撤去。この2スライスで grid ビューの db.query 全滅が完成。

---

## 27. 運用ルール: main 直コミット運用(2026-07-08 採用)

Phase 5 grid B1 以降、作業ブランチ(refactor/phase-N-XXX)の必須化を解除し、main への
直コミット運用を正式採用する(§20 の remote-control same-dir・1ブランチ積み上げと整合)。

**直コミット運用の規律(必須)**:
- 1コミット = 1目的を厳守し、revert 単位を小さく保つ。
- push は谷内さんの最終 GO 必須。「Don't ask again」は選ばない。
- 中間状態リスクのある撤去は1コミットで完結させる(§14-6)。
- Edit/Write は毎回 diff 提示 → 承認 → 適用。読み取り調査は一括可。

**緊急時の切り戻し**: git revert <hash> [--no-edit] → git push origin main
(Streamlit Cloud 自動デプロイで 3〜5分後に本番復旧)。複数コミットは新しい方から並べる
(git revert <new> <old> --no-edit)。

※ 本体(プロジェクトナレッジ)側は §8 Git ワークフロー 8.1 に「※ 2026-07-08 更新:
main 直コミット運用を採用」の注記で同期(ローカル控えは §8 が無いため §27 として独立記録)。

---

## 28. Phase 5 grid スライスB2/C: セレクタ + font read の service 化(grid db.query 全滅完成)(2026-07-09)

✅ grid.py に残っていた最後の db.query 2系統(プロジェクトセレクタ / フォント read)を
service 化し、**grid ビューの `db.query` を完全に 0 件化(grid 完全クローズ)**。
本番反映済み(origin/main = 075c6d2、実機テスト全項目合格)。main 直コミット。
これで Phase 5 の残りは **flyer ビューのみ**。

### 28.1 B2: セレクタの service 化(commit 1d6f70a)
- grid.py L72 の `db.query(TimetableProject).all()` を
  `project_service.list_projects_for_selector` に置換。
- **format_func 方式で id 逆引き**: selectbox の options に id を渡し label は
  format_func で生成。→ label が完全重複しても選択の同一性が壊れない
  (旧 {label:id} dict は label 衝突で最後の1件に潰れる)。widget key は付けない(無 key)。
- **意図的差分(改善方向・G5 合意済み)**: 日付なしプロジェクトのラベルを
  "None …" → "---- …" に変更。
- **parity 検証 4/4**: label 完全重複ケースで、旧 {label:id} は衝突・新方式は不壊、を
  対比 assert(scratch・DB 非書き込み・§12.4 方式)。
- **既知の潜在事項(B1 から継続)**: セレクタ/service の sort キー
  (x.event_date or "0000-00-00", reverse=True)は日付あり(date)と日付なし(文字列)混在で
  date と str 比較 TypeError の潜在リスク。grid・service 双方同一挙動のため B2 では触らず記録のみ。

### 28.2 スライスC: font read の service 化 + L61 db 撤去(commit 5932700 inert / 6640afe 置換)
- **共用 helper は無改造のまま、service ラッパで grid だけ移行**(罠32):
  - `get_sorted_font_list` / `create_font_specimen_img` は **4 ビュー共用**
    (grid/flyer/assets/timetable)。utils 側の定義・シグネチャは一切触らず、
    `font_service` が own_db を helper に渡す薄いラッパを噛ませて grid だけ移行。
    → 他3ビューに無波及(git diff 空で証明)。
- **grid 専用の `check_and_download_font` は `font_service.ensure_font_available` へ移設**。
  戻り値は4状態。
- **toast は view 戻し**: service は状態を戻り値で返し view 側が toast。`font_service` は
  **streamlit を import しない**(画面非依存=API/LINE Bot 化の前提 §11.3 を維持)。
- **新設2ファイル**: `repositories/font_repo.py` / `services/font_service.py`。
- grid.py L61 の `db=next(get_db())`(最後の db セッション)を撤去。
  → **grid.py の db.query が全滅、grid 完全クローズ**。
- **parity 検証**: 実 `font_service` を fake 依存でロードし、(1)ラッパ透過性、
  (2)DL 分岐 8 ケースが同一到達、を assert(scratch・DB 非書き込み)。
- 実機テスト全項目合格(toast の view 戻し・他タブ無影響を本番確認)。

### 罠32: 4ビュー共用 helper の service 化は「helper 無改造 + own_db を渡す service ラッパ」で1ビューだけ移せる
複数ビューが共用する helper(get_sorted_font_list / create_font_specimen_img 等)を
service 経由に移すとき、helper 本体のシグネチャを変えると全共用ビューに波及し、
罠19/20 級の広域改修になる。
→ 対処: helper の定義・シグネチャは触らず、service 側に「own_db(SessionLocal
  open→close 所有)を helper に渡すだけの薄いラッパ」を新設し、移行対象ビューだけを
  そのラッパに差し替える。他の共用ビューは helper を直接呼び続けるので **git diff が空**
  =無波及を機械証明できる。service は streamlit を import せず、画面依存(toast 等)は
  戻り値で view に返す。

---

## 29. Phase 5 flyer 移行: Phase 0 調査 + スライス F-rows(2026-07-10)

### 29.1 Phase 0 調査で確定した地形(読むだけゲート・コード変更ゼロ)
- 呼び出し元: workspace.py:92 render_flyer_editor(active_id)。project_id は workspace
  から確定済みで渡る=セレクタは flyer 内に無い(grid の B2 相当は不要)。
- 罠22 の切り分け(ORM 型で確定): flyer.py は2つの JSON を橋渡しするが別テーブル。
  - projects_v4.flyer_json(TimetableProject.flyer_json, database.py:79)= プロジェクト固有の
    フライヤー設定。書き手は apply_draft merge 一本(flyer.py は直書きしない=「2人目の書き手」
    問題無し。全置換せず動的キー消失防止)。
  - flyer_templates.data_json(FlyerTemplate.data_json, database.py:134)= 再利用プリセット。
    flyer.py のテンプレ CRUD と template.py が触る。projects_v4 とは別機能。
- flyer_json の動的キー: models/flyer_keys.py の FLYER_KEY_REGISTRY 106 エントリ
  (BASE 34 + STYLE 72、persist=True 103)。「動的」の正体は STYLE_PREFIXES 6 ×
  STYLE_PARAM_SPECS 12 の直積=固定72(アーティスト数依存ではない)。init=flyer.py:121-137、
  gather=36-42、draft 同期=session_manager.py:298-312、書き込み=project_repo.py:177-193(merge)。
- read escape: proj ORM(L76)が生成器/summary へ escape(DTO 化で解消可)。rows/asset は
  ローカル消費。「read ORM→write」結合は無い=artist の B' 再シーケンス不要(grid と同型)。
- widget 衛生(罠18): 大多数は key=SSOT で健全。flyer_date_format(index+外部書込)、
  flyer_grid_scale_h / flyer_tt_scale_h(widget所有 key へ外部書込)が §22 同型の要注意箇所だが
  移行のブロッカーではない。移行では「触らず温存」、改修は別 issue。
- session 残留(罠3): clear_project_session の dynamic_prefixes に "flyer_" 含む
  (Phase 2B-1c-①)。切替汚染は既に防御済み=移行で session 管理を触る必要なし。

スライス計画(inert→replace 2段・危険は後回し): F-C(font)/ F-rows(既存窓口)/
F-proj(proj DTO 化)/ F-asset(新 asset ドメイン)/ F-tmpl(flyer_templates CRUD の write、
template.py 同時載せ替え)/ F-db(db セッション撤去、生成器の db 依存を font パス事前解決へ)。
read 系 → write 系 → db 撤去の順。

設計判断(合意済み):
- font パス確保は font_service に新メソッド ensure_font_path を新設(既存 ensure_font_available
  =状態返し・grid が使用 は無改造=罠32)。
- F-tmpl は template.py を同時移行(commit 境界の二重化回避)。
- F-proj の DTO 網羅範囲 / F-db の生成器 db 用途 / F-asset の粒度(他 view の Asset read 分布)は
  各スライス着手時の Phase 0 で確定。

### 29.2 スライス F-rows: rows read の service 化(commit b26c2bc)
✅ flyer.py の TimetableRow read を既存 timetable_service.get_rows_for_project に一元化。
本番反映済み(origin/main = b26c2bc、実機テスト合格)。main 直コミット・単一コミット。

- 置換: L506 db.query(TimetableRow).filter(project_id).all() →
  timetable_service.get_rows_for_project(project_id)(grid B1 §26 で新設済みの既存窓口・無改造)。
  未使用化した TimetableRow import を撤去(grep 0件確認)。
- 意図的差分(機能等価・grid B1 と同型): L513 raw_order の明示ソート
  sorted(rows, key=lambda x: x.sort_order) を rows に。DTO(TimetableRowDraft, frozen)は
  sort_order を持たない(「並びはリスト内インデックスで決まる」設計)ため、load_rows の
  order_by(sort_order) 返却順に依拠。hidden_map(dict・順序無関係)と物販除外/is_hidden
  フィルタは DTO 属性(artist_name/is_hidden)の上に不変で維持。
- 事前確認で STOP→解決: DTO に sort_order が無く sorted(key=sort_order) が AttributeError に
  なるため、クロコが編集前に STOP 報告(DTO へフィールドを勝手に足さない=grid 共有で波及)。
  フィールド追加ではなく明示ソート除去で parity 維持する方式を採用。
- ガード検証: (1)sort_order は save_rows(timetable_repo.py:76)の enumerate 採番で de-facto 一意
  (スキーマ非強制・unique 制約は filename/name のみ)→ 正規保存で完全 byte parity。
  (2)tie 時も旧 .all() は ORDER BY 無し=既に DB 依存の非決定 → 新の order_by tie も DB 依存
  = 退化ではない。(3)rows の順序依存消費は raw_order のみ(hidden_map は順序無関係)。
- 検証: scratch/verify_flyer_rows_parity.py で filtered_artists の byte 一致を4形状
  (hidden 混在/sort_order バラバラ/空/重複名+tie)で機械証明・ALL PASS(DB 非書き込み)。
  py_compile COMPILE_OK、db.query(TimetableRow)/TimetableRow grep 0件、AppTest スモーク2本緑
  (test_smoke_all_tabs=flyer タブ例外ゼロ描画で新経路通過、test_no_value_bleed_on_switch=
  §22 回帰も継続緑)。実機テスト合格(概要テキストの並び=grid_order 未設定で sort_order 順 /
  非表示除外 / 物販除外 / 生成画像一致)。

flyer 残スライス: F-C(font)/ F-proj / F-asset / F-tmpl / F-db。次は F-C(font read の
service 化、ensure_font_path 新設)。

---

## 30. Phase 5 flyer スライス F-C: font read の service 化(2026-07-10)

✅ flyer.py の font read 5箇所(L81/L132/L364/L583/L590、移行前の行番号)を font_service 経由に
一元化。本番反映済み(origin/main = df26219、実機テスト合格)。main 直コミット・inert→replace の2コミット。

決定的発見(F-C/F-db 境界の確定): 生成器 create_flyer_image_shadow(flyer_generator.py:303)の
db= 引数は本体で完全未使用(grep "\bdb\b" が定義行のみ・db.query 0件)。get_font_path(同:332)は
FS だけで font を解決し db を使わない。よって F-C は生成器を一切触らず font read だけ移行でき、
生成器の db= 引数撤去は F-db に確定分離。前 Phase 0 で警戒した「生成器が db を要求するシワ」は
実在しなかった(デッド引数)。

設計判断(合意済み):
- ensure_font_path は「ラッパ方式」を採用(移設ではない): font_service.ensure_font_path(filename) は
  own_db を開き既存 utils.flyer_helpers.ensure_font_file_exists(db, filename) を無改造で呼ぶ透過ラッパ。
  → parity が透過性の証明だけで済み(4分岐 byte 再証明・撤去作業が不要)、罠19/20 リスクをゼロ化。
  grid C の get_sorted_font_list ラッパ(§28.2)と完全同型。ensure_font_file_exists は flyer 専用
  (呼び出し元 L583/590 のみ)だが utils に無改造温存(物理移動は F-db/Phase 6 の掃除に申し送り)。
- get_default_font_name は専用窓口を新設: font_repo.get_system_font_config(db)(純 read)+
  font_service.get_default_font_name()(.filename or "keifont.ttf")。SystemFontConfig read を
  font ドメインに集約(list_sorted_fonts の standard dict から派生させる結合を避けた)。
- ensure_font_available(grid 用・状態返し)は無改造。ensure_font_path(パス返し)と分岐が似ていても
  DRY 化せず2メソッド並存(grid の本番稼働メソッドを触らない=罠32)。

コミット構成(2段):
- 5732f6f(inert): font_repo.get_system_font_config、font_service.ensure_font_path(透過ラッパ)+
  get_default_font_name を追加。誰も呼ばない。streamlit 非 import 維持。
- df26219(replace): flyer.py の font read 5箇所を差し替え(→ list_sorted_fonts /
  get_default_font_name / build_specimen / ensure_font_path ×2)。未使用化した import
  (get_sorted_font_list / create_font_specimen_img / ensure_font_file_exists / SystemFontConfig)を
  grep 0件確認後に撤去。font_service import 追加。8+/10−。

検証(§12.4 方式・DB 非書き込み): scratch/verify_flyer_fc_parity.py で
(A)ensure_font_path の透過性(own_db 素通し・(db,filename) 素通し・戻り値透過・own_db close の7点)、
(B)get_default_font_name の2分岐(sys_conf あり→.filename / None→"keifont.ttf")が旧 L132-133 と
byte 一致、を fake 依存でロードして assert・ALL PASS。list_sorted_fonts/build_specimen の透過性は
grid C で実証済み。py_compile COMPILE_OK、撤去シンボル grep 0件、AppTest スモーク2本緑
(test_smoke_all_tabs=flyer タブ font 新経路で例外ゼロ描画)。実機テスト合格
(フォント selectbox / 見本画像 / 生成画像のフォント / fallback 既定 / 他タブ無影響)。意図的差分なし=機能等価。

事前確認4(build_specimen の透過性): flyer は font_list_data を未 sorted で直渡し、grid は
sorted で渡すが、build_specimen は内部 sort せず素通し(caller 側の差)。よって flyer の並びは不変=機能等価。

F-db への申し送り(F-C では触らない): ①生成器 create_flyer_image_shadow の未使用 db= 引数撤去、
②呼び出し側 db=db(flyer.py L609/625)除去、③flyer.py L75 next(get_db()) + L561 db.close() 撤去
(proj/asset/template の各 read が service 化された後)。

flyer 残スライス: F-proj / F-asset / F-tmpl / F-db。

---

## フェーズ計画 現在地(2026-07-10 時点)

- **Phase 5(残りビュー移行)**: artists **完了** / grid **完全クローズ完了**(§24〜§28)/
  **flyer 着手・F-rows(§29)+ F-C(§30)完了**(commit b26c2bc / df26219、本番反映済み)。
  flyer 残り = F-proj / F-asset / F-tmpl / F-db。
- flyer の論点(Phase 0 で確定予定): flyer_json の動的キー30+、罠18(widget SSOT・
  flyer_date_format の key 無し radio 等)、罠22(別テーブル flyer_templates.data_json との
  切り分け)、write 有無 / read escape / 既存窓口(list_projects_for_selector /
  get_rows_for_project / get_artists_by_names / font_service)で代替可否。
- 既知の制限(§21、保留継続): data_json 旧名 / loser 画像孤児化 /
  過去 merge の grid_order_json 残留の一括修復。いずれも慎重案件。
- テスト基盤: AppTest スモーク導入済み(§23)。flyer 移行時の回帰土台。
- 運用: main 直コミット(§27)。1コミット=1目的、Edit/Write は diff 提示→承認、
  push は谷内さんGO必須、本番データ保護モード厳守。
- flyer 完了後 → Phase 6 残り(型ヒント / キャッシュ最適化 / except:pass 撲滅 /
  罠7 毎レンダ ALTER TABLE 撤去)→ services 層の Web API 化(§11.7 段階A)→
  LINE Bot(§11.7 段階B1〜B4)。
