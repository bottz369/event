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

## 31. Phase 5 flyer スライス F-asset: Asset read の service 化(2026-07-10)

✅ flyer.py の Asset read 4箇所(L77/78 logo/bg 一覧、L565/570 .get(id))を汎用 asset ドメイン
経由に一元化。本番反映済み(origin/main = 6858785、実機テスト合格)。main 直コミット・
inert→replace の2コミット。

Phase 0 確定: flyer に Asset write 無し(db.add/commit は FlyerTemplate=F-tmpl 用)、Asset ORM は
生成器へ escape しない(渡るのは id / URL 文字列)、grid/artists に Asset read 無し。よって grid 型
(read のみ・B' 再シーケンス不要)。

設計判断(合意済み):
- 汎用窓口: repositories/asset_repo.py(list_assets_by_type / get_asset)+ services/asset_service.py
  (同 + AssetView 返し)を汎用設計で新設し、今回 flyer だけ載せ替え(他 view 無波及=罠32)。
  write(assets.py の Asset CRUD)は将来の assets ビュー移行スコープ。
- AssetView(id / image_filename / name)= selector と _generate_preview が読む最小集合。
- get_image_url は view に残す(案B): AssetView は image_filename まで、URL 化は view
  (render_visual_selector / _generate_preview)が呼ぶ。案A(service で url 解決)は AssetView 生成時に
  logo/bg 全件分 get_image_url を eager に呼ぶ=パフォーマンス懸念(罠16)+ get_image_url 内部未確認の
  ため見送り。案B で機能等価・変更最小。

コミット構成(2段):
- cb7908b(inert): models/asset.py(AssetView)、asset_repo.py、asset_service.py 新設。誰も呼ばない。
  streamlit 非 import。
- 6858785(replace): flyer.py L77/78 → asset_service.list_assets_by_type("logo"/"background")、
  L565/570 → asset_service.get_asset_view(id)。Asset import 撤去・asset_service 追加。get_image_url は
  view 温存。L74 db・生成器 db=db は温存(F-db 申し送り)。

検証(§12.4 方式・DB 非書き込み): scratch/verify_flyer_fasset_parity.py で (A)_to_view マッピング /
(B)list_assets_by_type 透過(asset_type 素通し・own_db close)/ (C)get_asset_view の Optional 挙動
ALL PASS。filter 条件 byte 一致(asset_repo の asset_type==引数, is_deleted==False が旧 flyer
L77/78 と同条件)を grep 対比。py_compile COMPILE_OK、flyer.py の Asset/db.query(Asset) grep 0件、
AppTest スモーク2本緑。実機テスト合格(ロゴ/背景 selector・生成画像反映・削除済み非表示・他タブ無影響)。

F-db への申し送り: _generate_preview の db 引数、生成器 db=db(L608/624)、flyer.py L74 db セッションは
F-db で撤去。F-asset 後に flyer.py が db を使うのは proj read(L75=F-proj)+ FlyerTemplate(F-tmpl)+
生成器デッド引数のみ。

---

## 32. 別件バグ修正: TT エディタ「2回目の編集が消える」(2026-07-10)

✅ flyer 移行とは別トラックの本番バグ修正。TT タブでセル入力→次のセル入力で2回目が消える
(出演順の selectbox 選択も同様)問題を根治。本番反映済み(origin/main = 945d422、実機テスト合格)。
main 直コミット・単一コミット(views/timetable.py +47行)+ 回帰網同梱。

症状: セルA入力→セルB入力(他操作なし)で2回目が消える。設定反映前にリロードで消えるのは
明示保存型の仕様(問題は2回目消失)。

真因(AppTest で機械再現・切り分け):
- 真因①(主): timetable.py の editor_df = draft_rows_to_df(draft_rows) を毎 run で作り直すため、
  前の編集が draft に入ると入力 df が変化 → data_editor が保留 edited_rows をリセット(Streamlit 既知
  挙動)→ 2つ目のセル編集が後段同期(L511)に届く前に破棄(tt_editor_key の bump は無関係。CASE_A で再現)。
- 真因②(副): 上流 widget(開演前物販 checkbox=keyless value=罠18、＋/削除/sort_items)が
  _bump_editor_seq()+st.rerun() を L511 より前に実行し保留編集を破棄(CASE_B で再現)。
- 明示保存型は守られていた(DB 保存は設定反映ボタンのみ=save_active_project L688)。session 同期の
  タイミング不具合。

採用方式: on_change 即確定案は AppTest で on_change が発火せず回帰検証不可のため不採用。代替の
「先取り確定(main-flow pre-read)」を独立 AppTest 実験で成立確認(2連続編集 99→77 が両方残る)→ 採用。

修正(commit 945d422):
- ヘルパー _apply_editor_state_to_df(edited_rows を positional 差分適用・純 pandas。num_rows="fixed"
  のため added/deleted は無視)。
- 「先取り確定」ブロックを draft_rows 取得直後・上流 widget 群(L405)より前に挿入:
  current_key(=f"tt_editor_{tt_editor_key}")の保留 edited_rows を draft_rows_to_df→_apply→
  df_to_draft_rows→_normalize_edited_rows で確定、!= ガードで set_draft_rows+mark_dirty。
  この時点の tt_editor_key は bump 前(前 run の編集を保持する key)。変換順は後段 L511 と同一で冪等。
  後段 L511 は保険として温存。
- これで①(再フィードリセット前に確定)②(上流 bump 前に確定)を1箇所で同時に解消。

検証(§12.4 方式・DB 非書き込み): 回帰網 tests/test_tt_editor_repro.py の CASE_A(純 data_editor
2連続編集)/ CASE_B(保留編集+checkbox toggle)を診断 assert から本物の回帰 assert に転じ、
修正前 RED(消える)→ 修正後 GREEN(両編集残存)を両ケースで実証。scratch/verify_tt_prewrite_parity.py で
(A)先取り適用==data_editor 内部適用 / (B)冪等性(2回適用==1回適用=二重適用が drift しない)/
(C)頑健性(None/空/範囲外/未知col)ALL PASS。§13.1 非回帰(開演前物販 goods_start_time が
open_time 追従・duration/adjustment=0 固定)OK。既存スモーク2 passed。実機テスト全項目合格。

変更範囲: views/timetable.py +47行のみ。services/models/DB 経路・save_active_project/apply_draft・
data_json には非接触(明示保存型・draft_rows 一本化・Phase 4 不変条件を維持)。回帰網
tests/test_tt_editor_repro.py を §23 の AppTest 基盤上に編入。

### 罠33: st.data_editor は「入力 df が変わると保留 edited_rows をリセットする」
draft を毎 run で df 化して data_editor に食わせ直す構造は、確定した編集が入力 df を変え、
data_editor が保留中の次の編集を捨てる(=2回目の編集が消える)。
→ 対処: data_editor 描画の「前」に、保留 edited_rows を SSOT(draft)へ先取り確定する
(上流 rerun / 再フィードより前)。適用の変換順を後段同期と揃えて冪等にし、後段は保険で残す。
上流 widget(bump/rerun 経路)より前に置くことで、key bump 由来の消失も同時に防げる。

### 罠34: AppTest(streamlit 1.50)は st.data_editor を操作できず on_change も発火しない
AppTest には data_editor の widget アクセサが無く、on_change コールバックも発火しない。
sort_items 等のカスタムコンポーネント(streamlit_sortables)は AppTest で非描画・非操作。
→ 対処: data_editor 依存の検証は session_state 注入(st.session_state[editor_key]=
{"edited_rows":{...}})で行う(main-flow の同期は注入で反映される)。on_change を必要とする
修正方式は AppTest で回帰検証できないため、中核修正では避け、main-flow で検証可能な方式を選ぶ。

---

## 33. Phase 5 flyer F-proj: proj read の service 化(2026-07-14)

✅ flyer.py の proj read(TimetableProject 直読み)を service 経由の読み取り専用 DTO へ移行。
本番反映済み(origin/main = 61ca4ad、実機テスト合格)。main 直コミット・2コミット
(inert b2bbf98 → replace 61ca4ad)。

- inert(b2bbf98): 生値ミラーの読み取り専用 DTO ProjectView(frozen, 13 フィールド)を
  models/project.py に新設。project_repo に to_flyer_view(生値 verbatim コピー)+
  get_project_view(未検出 None・commit しない read)、project_service に
  get_project_flyer_view(自前セッション open→map→close、ORM を外に出さない・
  意図的に非キャッシュ=直読みと同じ最新性)を追加。既存経路は無改造 → 動作不変。
- replace(61ca4ad): flyer.py L75 db.query(TimetableProject).first() →
  project_service.get_project_flyer_view(project_id)。未使用化した TimetableProject
  import を撤去(grep 0件)。db=next(get_db()) と _generate_preview(db, proj) は温存
  (proj は DTO になるだけ・属性 read のみで透過)。
- 設計判断(合意済み): 既存 ProjectDraft(編集用・to_draft で JSON 展開)は非流用。
  流用すると event_date が str→date、open_time が二重整形、tickets/grid が decoded 構造に
  なり byte-parity が崩れるため。ProjectView は「生値素通し」で flyer 側の json.loads /
  format_time_str / format_event_date をそのまま残し parity を保証(grid B1 §26 / F-rows §29 と同規律)。
- venue 注意: flyer L584 の getattr(proj,"venue","") は ORM に venue カラムが無く常に ""。
  DTO も venue フィールドを持たない → getattr 既定値 "" で同挙動(足さない・式を変えない)。
- read escape: proj は build_event_summary_text へは「値」を渡すだけ(ORM 本体は渡さない)。
  _generate_preview(db, proj) には proj を渡すが属性 read のみ・書き込み/再クエリ無し
  = read→write 結合なし(grid と同型)。書き込みは save_active_project(session_state 駆動)で別系。
- 検証: scratch/verify_flyer_proj_parity.py で消費値 byte 一致を5形状
  (full / all_none / empty_str / malformed_json / grid_no_order_key)で機械証明・PARITY_ALL_GREEN
  (DB 非書き込み・DB 非依存 = models/project.py をファイル直ロードし __init__/DB import を回避)。
  py_compile COMPILE_OK、flyer.py の TimetableProject grep 0件、AppTest スモーク2本緑
  (test_smoke_all_tabs が flyer タブを新経路で例外ゼロ描画)。実機テスト合格
  (会場/日付/サブタイトル/チケット/出演者並び/プレビュー/ZIP が従来通り)。
- F-tmpl / F-db への申し送り: flyer.py L74 の db セッションは FlyerTemplate CRUD(F-tmpl)と
  _generate_preview→生成器 db=db(F-db)がまだ使うため温存。F-proj 後に flyer.py が db を使うのは
  この2用途のみ。db 撤去は F-tmpl(write 移行・template.py 同時)→ F-db(生成器 db 依存を
  font パス事前解決へ)の順。

### 罠35(環境): Cowork/リモートの Linux VM から Mac の .venv・git は直接使えない
Cowork の device_bash は Linux VM で動くため、(1)macOS ビルドの .venv を exec 不可
(→ pytest / verify.sh は谷内さんの Mac ターミナルで実行)、(2)VM から接続フォルダの .git へ
commit するとファイル削除不可で index.lock / tmp オブジェクトが残置し、かつ identity 未設定で
fail(auto-detect した rcw-... は不正)。→ 対処: ファイル編集は VM 側で行い Mac へ書き戻す。
verify.sh / git add / commit / push は谷内さんの Mac ターミナルで実行(この分担が正)。
残置した index.lock は Mac で `rm -f .git/index.lock`、tmp は `find .git/objects -name 'tmp_obj_*' -delete`
で掃除。DB 非依存の parity 検証は models 単体をファイル直ロードすれば VM の system python3 で回せる。

---

## 34. Phase 5 flyer F-tmpl: テンプレート CRUD の service 化(2026-07-14)

✅ flyer.py と template.py(テンプレート管理ページ)の FlyerTemplate CRUD を新設 template
ドメイン(3層)へ移行。本番反映済み(origin/main = e159c46、実機テスト合格=create/同名エラー/
読込/上書き/一覧/名前更新/削除)。main 直コミット・2コミット(inert 87442e3 → replace e159c46)。

- inert(87442e3): template ドメイン3層を新設(誰も呼ばない)。
  - models/template.py: TemplateView(frozen DTO: id/name/data_json/created_at・data_json は素通し)
  - repositories/template_repo.py: list_templates(created_at desc)/get_by_name/create(add+flush)/
    update_data/rename/delete。commit しない・read は DTO で返す。is_deleted 列が無いため delete は
    物理削除(現行 template.py 挙動を維持)
  - services/template_service.py: list_templates/create_template(同名 False)/update_template_data
    (created_at も now 更新)/rename_template/delete_template。SessionLocal 所有・commit/rollback を握る・
    streamlit 非 import(画面非依存 §11.3)。created_at 形式 "%Y-%m-%d %H:%M:%S" を service で維持
- replace(e159c46): flyer.py と template.py を同時に service 化(①合意=commit 境界二重化回避)。
  - flyer.py: 一覧 db.query→list_templates、上書き→update_template_data、新規→create_template
    (同名チェック内包)。読込は target_t(DTO)の data_json を読むだけで従来通り(DB write 無し)。
    FlyerTemplate/datetime import 撤去。db は _generate_preview 専用に縮小し L73 コメントも更新(罠24)
  - template.py: 一覧→list_templates、名前更新→rename_template、削除→delete_template。
    get_db/FlyerTemplate/json/datetime import を全撤去(db セッションを view から一掃)
- 意図的差分: flyer.py の一覧順が Python sort(None 末尾)→ SQL ORDER BY created_at DESC(NULL 先頭)に。
  created_at は create/update 経路で必ず設定されるため実データ差は無く、template.py の既存 SQL 順に整合。
  新規作成失敗メッセージは「同名が存在します」に集約(旧: 同名は明示チェック・他例外は crash → service で
  例外も graceful に False+log 化。実質は同名時のみ発火)。
- 罠22 の再確認: flyer_templates.data_json(再利用プリセット)は projects_v4.flyer_json(F-proj)とは
  別テーブル・別責務。service は data_json を解釈せず素通し。
- 検証: py_compile / flyer.py・template.py の FlyerTemplate・db.query grep 0件 / verify.sh スモーク緑
  (flyer タブのテンプレ一覧が新経路描画。※書き込み・管理ページはスモーク対象外)/ 実機テストで
  create→同名エラー→読込→上書き→名前更新→削除を通し確認(テスト用テンプレ)。書き込み移行のため
  offline byte-parity 証明は非設置(DB 依存の commit/dup/delete は実機で検証=②a 合意)。
- F-db への申し送り: これで flyer.py の db(next(get_db()))は _generate_preview→
  create_flyer_image_shadow の db=db 専用。F-db = 生成器の db 依存(フォントパス解決等)を事前解決へ
  置換し、flyer.py の db セッション(next(get_db())/db.close())を撤去=flyer ビュー db 全滅で完了。

---

## 35. Phase 5 flyer F-db: 生成器デッド db 引数 + flyer db セッション撤去(2026-07-14)= Phase 5 完了

✅ flyer.py の db を完全撤去。これで flyer ビューの db 全滅 → **Phase 5(残りビュー移行)完全クローズ**。
本番反映済み(origin/main = 30a98d9、実機テスト合格=プレビュー画像 grid/tt 生成確認)。
main 直コミット・単一コミット(純デッドコード撤去のため inert 不要)。

- 発見: create_flyer_image_shadow(db, ...) の db は signature のみで本体未使用=デッド引数
  (生成器全体で db grep が def 行1件のみ)。フォントパス解決は F-C(§30)で font_service へ移済み
  → 生成器に db 依存はもう無かった(§34 申し送りの「font パス事前解決」は F-C で実質完了済みだった)。
- 撤去(30a98d9):
  - utils/flyer_generator.py: create_flyer_image_shadow の第1引数 db を削除
    (呼び出し元は flyer.py のみ・横断 grep 確認)
  - flyer.py: db=next(get_db())/db.close() 撤去、_generate_preview(db,proj)→(proj)(def+呼び出し3)、
    生成器呼び出しの db=db 撤去(grid/tt 2箇所)、get_db import 撤去(get_image_url は残置)、
    stale コメント2件(L73 の残置理由・L413「別 db セッション」)を撤去/DTO 前提に更新(罠24)。
- 挙動不変: db は誰も読んでいなかったため出力は完全に同一。session の open/close が消え、
  flyer レンダあたり DB コネクション1本分の固定費が減る副次効果のみ。
- 検証: py_compile / flyer.py・generator の db grep 0件 / verify.sh スモーク緑 /
  実機テストでプレビュー生成(グリッド版・TT版)の画像出力を確認。デッドコード撤去のため
  offline parity は非設置。

### Phase 5 総括(2026-07-14 クローズ)
残りビュー移行(artists / grid / flyer)を完了。DB=SSOT・3層(view→service→repo→model)・
read は DTO で返す・repo は commit しない・session と commit/rollback 境界は service が所有、
の規律を全ビューに適用しきった。flyer は F-rows / F-C / F-asset / F-proj / F-tmpl / F-db の
6スライスで db.query を全滅。次の主戦場は Phase 6 残り(型ヒント / キャッシュ最適化 /
except:pass 撲滅 / 罠7 毎レンダ ALTER TABLE 撤去)。

---

## 36. 段階A(Web API)事前調査: services の Streamlit 依存棚卸し(2026-07-14)

★読むだけ★調査(コード変更ゼロ)。LINE Bot §11.7 段階A の見積り精度を上げるため、
「API から services を叩くとき Streamlit(session_state / session_manager)にどこが縛られるか」を棚卸し。

### 最大の発見: session_manager は「壁」でなく API が使わない並行レーン
API はステートレスなので session_manager(draft/session_state モデル)を経由せず、綺麗な repo 層へ
直接降りられる。session_manager(st参照49)/ legacy_adapter(28)/ logic_project.py(28・旧世代)は
すべて UI 専用 → API は一切使わない。これが「見かけの重さ」の正体。

### 仕分け(3バケツ)
- ① そのまま API 化可(リファクタの成果):
  - read 系 service 全部(asset / template / timetable / artist / font / project read)= Streamlit 非依存確認
  - repo の write 全部(project_repo.update_project_from_draft / timetable_repo.save_rows /
    artist_repo.* / template_repo.*)= db+データのみ・session_state 不使用
  - grid 画像生成 generate_grid_image = 引数で全パラメータ受領済(パラメータ化済)
  - 概要テキスト build_event_summary_text / flyer 合成 create_flyer_image_shadow(§35 で db も除去)= 純粋関数
- ② 軽い手入れ:
  - TT 画像生成 generate_timetable_image = 中に st.toast(L216)/ st.error(L281)が2つ埋まるのみ
    (他の "st." は Artist. の grep 誤検出)→ 戻り値化で API 可
  - project_service.list_projects_for_selector は @st.cache_data 付き → API は素の
    project_repo.list_projects 直呼びで回避
- ③ ステートレス再設計が要る(段階A の本当の作業):
  - write オーケストレーション: save_active_project 等は session_manager 依存 → API は迂回し、
    リクエスト JSON → ProjectDraft/rows を組んで repo write を直叩きする薄い関数を新設(機械的・中)
  - flyer 生成オーケストレーション: _generate_preview が session_state から flyer_* を集める →
    API 版は projects_v4.flyer_json + assets から styles を組む DB 駆動版を新設
    (段階A 唯一の "新規ロジックらしい新規"・中)

### 結論: 段階A は「中」(想定より軽い)
リライトではなく「薄いラッパ + flyer 生成オーケストレーター1個」。3層リファクタで
read / repo write / 画像生成 core が既に API-ready だった。最薄 MVP = read 系 + grid/TT/text
生成トリガー(①②ほぼ素通し)から出し、write と flyer は後追い。B4(アー写更新・LIFF 不要)を
最初の実運用機能に前倒しできる(§11.7)。

### 段階A 着手時の Phase 0 で詰める点
- ステートレス write 関数のシグネチャ(API payload → ProjectDraft/rows 変換の置き場)
- flyer styles の DB 駆動 gather(FLYER_KEY_REGISTRY を session_state でなく flyer_json 起点に)
- generate_timetable_image の st.toast/error 除去の可否(views 側へ戻り値で通知)
- 認証 / 案件ID⇔LINEグループID テーブル / ホスティング(無料枠)選定

---

## 37. Phase 6: 罠7(毎レンダ ALTER TABLE)撤去 = TT 自動マイグレーション削除(2026-07-14)

✅ views/timetable.py の check_and_migrate_add_goods_columns(timetable_rows に
ALTER TABLE ADD COLUMN ×3 を起動時に走らせる自動マイグレーション)を完全撤去。
本番反映済み(origin/main = b198ebe、本番3カラム存在を read-only SELECT で確認済み)。
main 直コミット・単一コミット(純撤去・-43行)。

- 背景: 罠7 は「毎レンダ ALTER TABLE」。Phase 3 Fix2(df1a52c)で @st.cache_resource による
  プロセス1回化までは済んでいたが、関数自体の撤去は timetable.py 全面書き換え待ちで保留されていた。
- 撤去(b198ebe): check_and_migrate_add_goods_columns / _ensure_goods_columns_migrated(cache ラッパ)/
  render_timetable_page L228 の呼び出し / 未使用化した `from sqlalchemy import text` を削除。
  SessionLocal は別箇所(temp_db)で使うため残置。
- 安全確認(罠31): 3カラム(add_goods_start_time / add_goods_duration / add_goods_place)は
  ORM(database.py TimetableRow L103-105)に定義済 → 新規 DB は create_all で作られる。本番は既存 →
  scratch/check_goods_columns.py の read-only SELECT(information_schema.columns)で3カラム存在を確認
  → ALTER は本番で既に no-op、撤去は挙動不変。
- 検証: py_compile / timetable.py の ALTER・check_and_migrate・text grep 0件 / verify.sh スモーク緑
  (TT タブ描画=撤去経路を直接通る)/ 実機テスト(TT 編集・保存)。冪等 no-op 撤去のため parity 非設置。
- 残る render 経路の DDL は init_db の Base.metadata.create_all(CREATE TABLE IF NOT EXISTS・冪等・
  @st.cache_resource で1回)のみ = 正当な初期化で罠7 の対象外。migrate.py(SQLite 手動スクリプト)は
  render 経路外の旧世代物で今回対象外(別途整理候補)。

---

## 38. Phase 6: 裸 except(`except:`)撲滅 = except Exception 一律化(2026-07-14)

✅ アプリ本体の裸 except 40箇所を `except Exception:` に一律置換。本番反映済み
(origin/main = 7c6bc3b、verify.sh 緑・実機軽確認)。main 直コミット・単一コミット(12ファイル・40/40)。

- 背景: 裸 except は KeyboardInterrupt/SystemExit/GeneratorExit まで飲み込む(Ctrl+C 無効化・
  プロセス終了の握り潰し)。40箇所すべて「try: 危険処理 → except: フォールバック」の防御パターンで、
  バグ隠しや特定例外に絞るべき箇所は無し(全件文脈確認済み)。
- 方針: `except Exception:` へ一律絞り込み。通常例外(ValueError 等)の捕捉は完全に不変=挙動不変で、
  KeyboardInterrupt/SystemExit だけ正しく伝播するようになる。ログ(可視化)は hot-path フォールバック
  (フォント/色/JSON parse)にノイズを増やすため今回は入れず、意味のある失敗箇所だけ後で選別する別パスにする。
- 実装(罠19/27 準拠: スクリプト+機械証明): scratch/fix_bare_except.py で行頭アンカー正規表現
  `^(\s*)except\s*:` → `\1except Exception:`(コメント/文字列内の "except:" は行頭 except で始まらず
  非マッチ=誤爆なし)。冪等(再実行で except Exception: は非マッチ)。
- 機械証明: 置換前 40 → 後 0、全 .py py_compile 緑、git diff は 40挿入/40削除で「except を含まない
  変更行=0件」を grep 確認(=except 行のみの変更)。内訳: flyer_generator 9 / flyer 8 / utils/__init__ 6 /
  timetable 3 / logic_grid 3 / grid 2 / assets 2 / flyer_helpers 2 / logic_project 2 / projects 1 /
  overview 1 / logic_timetable 1。tests/ は裸 except 0件で対象外。
- 残タスク(将来・選別式): 意味のある失敗箇所への logger 追加(§11.3 の可視化)。hot-path 以外を対象に。

---

## 39. Phase 6 クローズ: 型ヒント(コア公開API)+ キャッシュ現状維持決定(2026-07-14)= Phase 6 完了

✅ Phase 6(残りリファクタ)を honest にクローズ。本番反映済み(origin/main = 066e91d)。

- 型ヒント(commit 066e91d): コア公開 API を実質100%型付け。
  - 事前調査: repositories 43/43=100%、services 47/42、models は公開 dataclass メソッド全て型付け済
    (未型付けは private/nested ヘルパーのみ=_to_int / _normalize_cell 等)。
  - 実施: services の未型付け公開4関数に注釈追加 — font_service.list_sorted_fonts() -> List[dict] /
    build_specimen() -> PIL Image(TYPE_CHECKING ガードで実行時 import 回避) / ensure_font_path() ->
    Optional[str] / project_service.list_projects_for_selector() -> List[Tuple[int, str]]。注釈のみ=実行時挙動ゼロ変化。
  - スコープ外(決定): views / utils(Streamlit UI・PIL 生成層。ほぼ -> None で価値薄・工数大)と
    private/nested ヘルパーは対象外。将来の該当ファイル書き換え時に随伴で付ける。
- キャッシュ最適化(コード変更なし・決定を文書化): 効くキャッシュは既に導入済み
  (init_db=@st.cache_resource / project_service.list_projects_for_selector=@st.cache_data+手動 clear /
  views/artists.py の一覧)。これ以上の追加は罠17(全 CRUD 経路の invalidation 設計とセット)の
  リスク > 価値のため defer。「現状で最適」と確定。

### Phase 6 総括(2026-07-14 クローズ)
Phase 6(残りリファクタ)完了。内訳: 死コード掃除(先行)/ 罠7 撤去(§37)/ 裸 except 撲滅(§38)/
型ヒント コア公開 API(§39)/ キャッシュ現状維持決定(§39)。→ **リファクタ全体(Phase 1〜6)が完了**。
次の主戦場は LINE Bot §11.7(段階A: Web API・§36 で「中」規模と判明)。残る低優先(随伴で):
views/utils の型ヒント・選別式 logger(§38)・型ヒント private ヘルパー。

---

## 40. LINE Bot B4 実装計画: アー写更新の縦スライス(2026-07-14 設計・合意)

§11.7 の「B4(アー写更新・LIFF不要)を最初の実用機能に前倒し」で建設フェーズに着手。最新事実
(LINE Messaging API / 無料ホスティングの常時起動性)を web 確認した上での設計。3大決定を合意済み。

### 決定事項(2026-07-14 合意)
1. 進め方 = **B4 から縦に貫く**(「動くものを早く」)。最小 Bot + アー写更新で「動く LINE Bot」を最速体験。
2. アーキテクチャ = **モノリス Bot**。event-app リポジトリに新規 `bot/main.py`(FastAPI Webhook)を足し、
   既存 services を直 import する。段階A(別立て Web API)は今は作らない(LIFF が要る B2/B3 で分離)。
   根拠: §36 + 今回のリファクタで artist_service は画面非依存(streamlit / session_manager 非依存)→ Bot 直呼び可。
3. ホスティング = **Railway 等 ~$5/月・常時起動**(cold start なし)。Webhook は応答性が要るため無料スリープ枠
   (Render 無料=15分スリープ・30〜50秒 cold start)は避ける。

### B4 フロー(縦の1本)
Webhook 受信 → 署名検証(X-Line-Signature = channel secret の HMAC-SHA256) → ガード(グループ許可リスト /
送信者 = 谷内さん userId / mention.mentionees[].isSelf でボット宛て判定) → テキストからアーティスト名抽出
("バンドAのアー写更新"→"バンドA") → 画像 DL(GET api-data.line.me/v2/bot/message/{messageId}/content,
Bearer access token) → artist_service.get_artists_by_names で特定 →
artist_service.update_artist(id, name, image_file=DL画像) で画像のみ差し替え → reply/push で谷内さんに結果通知。

### 新規実装は薄い層のみ(既存 service 再利用)
再利用: get_artists_by_names / update_artist(画像のみ差し替え・name は既存維持)/ upload_image_to_supabase
(update_artist 内部)。新規は「Webhook 受信・LINE 署名検証・画像 DL・名前抽出・通知・グループ/送信者ガード」だけ。
依存追加: fastapi / uvicorn / line-bot-sdk(または生 HTTP)。

### 谷内さんの準備作業(アカウント系・私は手順ガイド)
1. LINE Developers で Messaging API チャンネル作成 → channel secret / channel access token 取得。
   グループ参加を許可・応答メッセージ(自動応答)OFF・あいさつOFF。Webhook URL は Railway デプロイ後に設定。
2. Railway アカウント作成(デプロイ先)。
3. secrets(LINE の secret/token・Supabase)はホストの env / ローカル手動配置。**コミットしない**(.gitignore・請求書アプリ流儀)。

### 注意 / セキュリティ
- アー写はアーティストDB全体で共有 = 更新は他イベントのグリッドにも波及(通常は正)。将来の顔認識キャッシュ導入時は
  アー写更新でキャッシュ再計算トリガーが要る(§11.7 の申し送り)。
- DM完全無視 / グループ許可リスト / 編集系は谷内さんID限定 / 署名検証必須(§11.2 の Bot 骨格原則)。

### 実装ステップ(予定)
(a)谷内さん: LINE チャンネル作成 → secret/token を私に伝えず手元保管。
(b)実装: bot/main.py(Webhook + 署名検証 + ガード + 名前抽出 + 画像DL + service 呼び + 通知)、requirements、Railway 設定。
(c)デプロイ: Railway に push → Webhook URL を LINE に登録 → グループに Bot 招待。
(d)実機テスト: テスト用アーティストで "@Bot ○○のアー写更新"+画像 → 差し替え確認(本番データ保護: テスト用のみ)。

---

## 41. LINE Bot B4(アー写更新)デプロイ完遂 = 本番稼働開始(2026-07-16)

✅ §40 で設計・実装した B4(アー写更新)を Railway にデプロイし、実機テスト合格。本番稼働開始。
LINE グループで「@BOTTZ AI <アーティスト名>のアー写更新」+画像 → Storage/DB 反映まで end-to-end で成功
(テスト用アーティスト「テスト太郎」で更新確認、サイト側でも差し替えを目視)。本番 Streamlit は全工程で無停止。

### コミット / 変更
- 577d302: bot 依存分離(bot/requirements スリム + database.py の optional streamlit import + Dockerfile 追加)。
- fd52c37: Docker イメージにアプリ全依存を導入(root requirements.txt を COPY→install。pandas 欠落の修正)。
- e1314b5: Docker ベースを python:3.11-slim → python:3.13-slim(本番と一致、numpy==2.5.1 対応)。
- Railway ダッシュボード: Custom Start Command を空に(コミット外の設定修正。罠36)。

### 依存共存の確認(577d302 の判断根拠)
※ **§42 で訂正**: この節の当初結論「streamlit と fastapi は共存可能(starlette 0.41.3 で無害)」は**誤り**。正しい事実は下記。
- streamlit 1.59.2 は内部で starlette を使う(tornado から移行済み)。
  `streamlit.web.server.starlette.starlette_gzip_middleware` が `starlette.middleware.gzip.DEFAULT_EXCLUDED_CONTENT_TYPES`
  を import し、このシンボルは **starlette 0.46.0 で追加**。→ streamlit 1.59.2 は **starlette>=0.46** が必要。
- fastapi 0.115.6 は **starlette>=0.40,<0.42** を要求。
- ∴ 版数範囲が重ならず**両立不可**。両方入れると starlette が 0.41.3 に固定され、streamlit の import が ImportError になる。
- 本番 Streamlit Cloud が正常なのは fastapi のピンが無く starlette>=0.46 が入るから。Bot(Railway)は fastapi 0.115.6 を
  入れるため starlette 0.41.3 となり、streamlit を import する連鎖があると落ちる。
- **回避策(正)**: 版数で両立させようとせず、**Bot の import 連鎖を streamlit 非依存にする**(§11.7 段階0)。root に streamlit が
  入っていること自体は事実だが、「無害だから共存できる」のではなく「Bot が streamlit を import しなければ問題ない」が正しい。
  実際 LINE Bot /callback(アー写更新)は import 連鎖に streamlit を含まないため B4 は動いていた。壊れたのは新規 /api だけ
  (project_service が streamlit を引くため)で、§42 の非依存化(commit 8af2d69)で解消。詳細は罠39。
- 以前の本番クラッシュ(root に fastapi を足した d1926ad → revert 59535a0)は fastapi のピン欠如で starlette が streamlit の
  要求と食い違ったのが発端。fastapi==0.115.6 の明示ピン+Bot の streamlit 非依存化で決着。
- Docker は root+bot 両方を install する full install 方針でよい(streamlit も入るが Bot が import しなければ無害)。

### 系統の違いを常に意識(今回の3罠の根)
本番 Streamlit(Streamlit Cloud)は Dockerfile を無視し requirements.txt を見る。Bot(Railway)は Dockerfile を使う。
ビルド系統が別なので、片方だけで起きる問題(依存欠落・Python 差)が出る。

## 罠36: Railway の Custom Start Command が Dockerfile CMD を握り潰す
Railway のサービス設定(Settings→Deploy→Custom Start Command)にスタートコマンドが残っていると、Dockerfile の CMD より
優先され、しかも exec 的に渡されて $PORT がシェル展開されない。
症状: Deploy ログに Error: Invalid value for '--port': '$PORT' is not a valid integer. が延々 = crash loop。
リポジトリの Dockerfile CMD は正しい(["sh","-c","uvicorn ... --port ${PORT:-8000}"])のに直らない、が目印。
対処: Custom Start Command を空にして Dockerfile CMD を使わせる(または sh -c '... ${PORT:-8000}' を設定)。
教訓: リポジトリ外(ホストのダッシュボード)の設定がコードを上書きする。コードを直す前にホスト設定を疑う。

## 罠37: Docker の bot 依存をスリムにしすぎて共有コードの実行時依存が欠落
「bot は streamlit 非依存だからスリムに」と bot/requirements.txt を絞ると、共有コード(models/services)が実行時に import する
pandas 等が Docker イメージに入らず import 連鎖で落ちる。
症状: ModuleNotFoundError: No module named 'pandas'。実際の失敗地点は from services import artist_service → models/timetable.py の import pandas。
webhook 応答自体は 200 でも更新処理だけ落ちるので気づきにくい。
対処: Bot イメージは bot.main が transitively import する全依存を入れる。root requirements.txt を Docker で COPY→install。
注意: bot/requirements.txt の -r ../requirements.txt は、pip install より前に root requirements.txt を COPY しておかないと解決できない(COPY 順序依存)。

## 罠38: Docker ベースイメージの Python が本番とズレると本番のピン依存が解決不能
本番(Streamlit Cloud=Python 3.13)で入るピン留め依存が、Docker(python:3.11-slim)では解決できない。
症状: No matching distribution found for numpy==2.5.1(numpy 2.5.1 は Requires-Python >=3.12)。ビルドが依存解決フェーズで即 FAILED(起動前)。
対処: Docker のベースイメージの Python を本番に合わせる(python:3.13-slim)。
教訓: 同じ requirements.txt を別 Python で入れると解決結果が変わる。デプロイ環境の Python は本番に揃える。

## 42. 段階A0(read API + API キー認証)完了 = 本番稼働(2026-07-16)

✅ §11.7 段階A の入口として、Bot と同一 FastAPI アプリに **read 専用 /api** を追加し、API キー認証を付けて本番稼働。
本番実データで動作確認済み(EVENT_API_KEY を Railway に設定 → `GET /api/projects` が実プロジェクト一覧を返すことを curl で確認)。

### 設計(Phase 0 決定)
- 置き場所: 別サービスにせず bot/main.py の FastAPI app に APIRouter を include_router で mount(モノリス)。
- 範囲: **read のみ**(GET・非書き込み)。生成/write は今回入れない(A1/A2)。
- 認証: env 単一共有キー `EVENT_API_KEY` を `Authorization: Bearer <key>` / `X-API-Key` と `hmac.compare_digest` で照合。
  未設定/不一致は 401(**fail-closed**)。Webhook(/callback)の LINE 署名検証とは**別系統**。
- project_id は API がパラメータで直接受け取る(グループID紐付けテーブルは無し)。

### read エンドポイント 5 本(DTO を JSON 返し・ORM は返さない)
- `GET /api/projects`(一覧: id/title/event_date)/ `GET /api/projects/{id}`(ProjectView 相当)/
  `GET /api/projects/{id}/rows`(TimetableRowDraft)/ `GET /api/projects/{id}/grid`(grid_order・None安全)/
  `GET /api/artists`(ArtistView)。未検出 id は 404。

### 検証
- TestClient ユニット/機械証明テスト 16 件(認証 401・各 GET・404・grid の None/空/壊れ JSON)。
- streamlit 不在を強制した import 非依存テスト(read 経路が streamlit/session_manager を引かないことを機械証明・aab86b7)。
- 本番実データで curl 確認(/api/projects が実プロジェクト一覧を返す)。

### 罠(500 → 非依存化)
本番実データで /api が 500。原因は project_service の import 時に `import streamlit` / `@st.cache_data` /
top-level `from services import session_manager`(streamlit を引く)が評価されるため。版数では両立不可(罠39)なので、
**project_service の read 経路を streamlit/session_manager 非依存化**して回避(§11.7 段階0):optional import(`try/except`→`st=None`)+
`@st.cache_data` の no-op 退避(`.clear()` 互換)+ session_manager を write/session 関数内の**遅延 import** 化。
artist_service は元々非依存(/api/artists は当初から可)。

### コミット(本番反映済み)
- 4a6e5c9(骨格 + API キー認証 + mount)/ dab3c1d(TestClient テスト)/ f98fe91(grid の None 安全化 + N+1 確認 + EVENT_API_KEY doc)/
  8af2d69(project_service を streamlit/session_manager 非依存化)/ aab86b7(import 機械証明テスト)。

### 次
- A1: grid 画像・告知テキストの**生成トリガー**(§36 バケツ①)。その後 A2: TT 生成(st.toast/error 除去を伴う)。

## 罠39: streamlit 1.59.2 と fastapi 0.115.6 は starlette 版数で両立不可
streamlit 1.59.2 は starlette>=0.46 が必要(`DEFAULT_EXCLUDED_CONTENT_TYPES` が 0.46 で追加)、fastapi 0.115.6 は starlette<0.42。
同一環境に両方入れると starlette が **0.41.3 に固定**され、streamlit の import が ImportError になる。
症状: streamlit を引くモジュールの import 時に `ImportError`(fastapi 側の環境で streamlit を import した瞬間)。pip の依存解決は
通ってしまうことがある(fastapi のピンが勝って古い starlette が入る)ため、install 成功=動作可能 ではない。
対処: **版数で両立させようとしない**。streamlit を使う側(Bot の import 連鎖)を streamlit 非依存にして回避する(§42・§11.7 段階0)。
教訓: 「import できる/依存が競合しない」は、実際にそのモジュールを import して確かめる。fastapi だけ import して streamlit を
試さないと見逃す(**pip の解決が通る ≠ runtime import が通る**)。

## 43. TT タブ 4 機能追加(一括追加 / 一括削除 / アー写グリッド表示順 / アー写グリッド非表示)(2026-09-01)

✅ タイムテーブルタブに 4 機能を追加し、アー写グリッドの並べ替えを TT に一本化した。
すべて明示保存型(操作は draft_rows / session のみ、DB 反映は「🔄 設定反映」だけ)。
本番反映済み(origin/main = `f2d11ae`)。**DB スキーマ変更ゼロ**。

### 実装した 4 機能
- **③ アーティストの一括追加**(`c66a398` / `cae8d87` / `c8b2e98`): 候補 multiselect →「追加予定リスト」に溜める →
  `sort_items` でドラッグ並べ替え + × ボタンで除外 →「追加する」で出演順の末尾へ一括 append。
  予定リストの操作中は DB 保存しない。★ここで新設した `sort_items` には **`key=` を明示**した(下記)。
- **① 行の一括削除**(`96b0f84` / `2c9a270` / `7664cc8`): 「削除」チェック列 →「🗑 チェックした行を削除」で一括除去。
  特殊行(開演前/終演後物販)は対象外(増減は専用トグルが正)。
- **② アー写グリッド表示順**(`bb5294b` / `fae9b59` / `f6dc2f0` / `898e38d`): TT に番号列を追加し、
  番号の昇順で左上から詰める。**views/grid.py のドラッグ&ドロップ並べ替えを撤去**し、TT の番号を並び順の唯一の正にした。
- **アー写グリッド非表示**(`cf4411e` / `c4a7f5f` / `ae8e70a` / `f2d11ae`): 既存 `IS_HIDDEN` の表示名を
  「タイムテーブル非表示」に改名し、グリッドの除外条件を新フラグ `is_grid_hidden` へ移設。
  2 つは独立(TT 画像から消してもグリッドには出る。逆も同様)。

### ★確立したパターン: DB スキーマを変えずに UI 列を増やす
`timetable_rows` に空きカラムが無く、スキーマ変更は禁止。そこで **`TimetableRowDraft` の非永続フィールド**として
列を持たせ、永続化が要るものだけ `grid_order_json`(JSON カラム)に畳む形に統一した。

1. `TimetableRowDraft` に非永続フィールドを追加(`is_delete_marked` / `grid_no` / `is_grid_hidden`)。
2. `TIMETABLE_DF_COLUMNS` に対応列を追加(`DELETE` / `GRID_NO` / `GRID_HIDDEN`)+
   `to_legacy_dict` / `_DF_KEY_TO_DRAFT_KEY` / `from_dict` に写像を足す。
3. `repositories/timetable_repo.py` は**無変更**(`_draft_to_row` が書き出さない = 保存→再読込で必ず初期値に戻る)。
4. 永続化が要るものは **grid_settings に seed / save**:
   - save: 「設定反映」の `save_active_project()` **直前**に純関数で名前リストへ畳む
     (`build_grid_order_from_rows` / `build_grid_hidden_from_rows`)。**新しい保存境界は作らない**。
   - seed: `session_manager.reload_project()` の **`_save_snapshot()` より前**に復元する
     (`seed_grid_no_from_order` / `seed_grid_hidden_from_settings`)。
5. 未保存判定(`_rows_to_comparable`)は「保存内容を左右するか」で入れる/入れないを決める:
   - `is_delete_marked` は**含めない**(チェックしただけで誤警告が出る)
   - `grid_no` / `is_grid_hidden` は**含める**(保存される並び順・除外を変えるため、含めないと黙って失われる)

### ★罠33 対策が load-bearing(3 機能とも RED 証明済み)
新設の UI 列は **必ず `draft_rows_to_df` が出す列にすること**。UI 専用の session に別持ちすると、
views/timetable.py の「先取り確定」(`_apply_editor_state_to_df` の `if col in new_df.columns` ガード)に
弾かれてチェックが毎 run 捨てられる。しかも実害は「黙って捨てられる」より悪く、
**Streamlit の `_apply_cell_edits` が `KeyError` を投げて画面ごと壊れる**。
`TIMETABLE_DF_COLUMNS` から該当列を 1 行抜いた木で `DELETE` / `GRID_NO` / `GRID_HIDDEN` の 3 つとも RED を機械確認した。

### seed の位置(誤「未保存」警告の罠)
`grid_no` / `is_grid_hidden` は `_rows_to_comparable` に含めるため、**seed を `_save_snapshot()` の後で行うと
プロジェクトを開いた瞬間に「⚠️ 未保存の変更があります」が出る**。当初は view 側で採番する設計だったが、
この理由で `reload_project()` 内(snapshot 前)へ移した。回帰網 `test_no_false_unsaved_warning_on_open` で固定。

### grid DnD 撤去(`898e38d`)
- 撤去理由: 1 ドラッグで「component の値返し + `st.rerun()`」の 2 回スクリプトが走り、
  workspace の `st.tabs` が全 4 タブを毎回 eager 描画するため重い。加えて `sort_items` を **`key=` 無し**で
  呼んでいたため items が変わるたびにコンポーネントが再マウントして状態を失い、
  古い戻り値と新しい値が ping-pong して操作不能になることがあった(`grid_just_reset` はその場当たり対処)。
- 併せて **競合 writer** も撤去: 「grid_order が空なら TT の逆順で埋める」初期化と、リセットボタンの order 書き戻し。
  残すと他タブの保存で `sync_session_to_draft` が拾い、DB の order が TT の番号と食い違う。
- 撤去は AST(`ast.unparse` でコメントを落としたコード)+ 文字列の両方でゼロ件を機械証明した(罠29 の流儀)。
  この過程で未使用になった `timetable_service` import も検出できた。

### 移行(既存データの見た目を保つ)
- ②: 読込時に `grid_order["order"]` 内の位置 + 1 を `grid_no` に seed → 番号列を足しても初期表示は従来どおり。
- グリッド非表示: `grid_settings` に `grid_hidden` **キーが存在するか**で移行判定する(値の truthiness ではない)。
  キーが無い未移行プロジェクトは `is_grid_hidden = is_hidden` で引き継ぐ。
  **空リストは「誰も非表示にしていない」という確定状態**で、未移行とは別物。`or` で判定すると空リストが
  未移行に化けて引き継ぎが誤発火する。よって save 側は該当ゼロでも必ず `[]` を書き出す。
- read-only SELECT で影響を確認(全 21 プロジェクト): `grid_hidden` キー既存 = **0 件**(全件が未移行経路)、
  `is_hidden=true` の行を持つ = **9 件**(中身はほぼ「転換 / 調整 / OPEN / 会場入り / 完全撤退」等の運用行)。
  「TT にいない登録アーティストが保存時に order から落ちる」仕様変更の影響 = **0 件**。
  段階② で撤去した旧ハードコード除外 `["転換","調整"]` に該当し `is_hidden=false` の行も **0 件**。

### 申し送り
- views/timetable.py 左「出演順」の `sort_items` は **まだ `key=` 無し**(③で新設した予定リストだけ `key` 付き)。
  ping-pong バグの元が残っているので別スライスで付与する。
- 同名重複行があると、左「出演順」のドラッグで `name_to_row` の dict 化が重複を潰し、**行が黙って消える**
  既存バグがある(CSV 取込は重複名を許すため発生しうる)。恒久対処は index ベースのキーに変える。
- 概要 / フライヤーの**告知テキスト**の出演者リストは引き続き `is_hidden`(タイムテーブル非表示)で除外する。
  グリッドの新フラグは効かない。寄せるかは未決。

## 44. 段階B(LINE からのフライヤー / TT 更新フロー)設計(2026-09-01 設計・合意)

⏳ **設計のみ・未実装**。グループ LINE から「アー写を差し替えて、フライヤーとタイムテーブルを再生成して返す」フロー。

### 決定事項
- **グループ⇔プロジェクトの紐付けはしない**。制作部門の 1 グループで全イベントを扱うため、
  グループ ID とプロジェクトを対応させる意味が無い。対象イベントは毎回その場で選ばせる。
- **トリガー1(差し替え)**: 「〇〇の写真差し替えて」+ 新アー写 → アー写更新(全イベントに反映・既存 B4 §40/§41)
  → **〇〇が出演する直近イベント**をボタンで提示(出演者で絞り込む)→ 選択 → フライヤー + TT の 2 枚を再生成して返信。
- **トリガー2(単体取得)**: 写真を変えず「最新ちょうだい」→ 直近イベントを提示 → 選択 → 2 枚返信。
- **権限**: グループの誰でも可(便利さ優先。問題が出たら絞る)。確認ステップは挟まず即更新(B4 の踏襲)。
- **返す成果物**: フライヤーセットの「フライヤー」「タイムテーブル」の **2 枚のみ**。
  アー写グリッド・告知テキストは対象外。

### 新規開発(実装スライス案・この順)
1. **フライヤー画像の API 化**(最大の実装)。論点は `flyer_json` の動的キーが 30+ あること(§33〜§35 / 罠22 参照)。
2. **タイムテーブル画像の API 化** = 段階A2 で後回しにした §36 バケツ②。
   `generate_timetable_image` の `st.toast` / `st.error` を戻り値化する必要がある。
   **4 ビュー共用の関数なので画像 parity に注意**(罠32 の「helper 無改造 + own_db を渡す service ラッパ」が使えるか要検討)。
3. **Bot 会話フロー**: アー写更新 B4 → 出演イベントで絞り込み → イベント選択ボタン(LINE クイックリプライ)
   → 2 枚生成 → Storage 経由で LINE 返信。トリガー2 も同じ経路に載せる。

### 流用できる資産
- LINE Bot 本体(Railway / Docker、§41)とアー写更新 B4(§40 / §41)。
- grid 画像の API 化で得た知見: フォント materialize(罠40)/ OOM 対策(取得時 downscale +
  JPEG draft デコード + `_render_lock` による直列化)/ Storage 経由の画像返却。
- `GET /api/projects`(§42)= 直近イベントの取得。

## 45. 段階A1(生成トリガー)/ A2(grid 画像の実運用ハードニング)(2026-07-16〜2026-09-01)

✅ 実装済み・本番稼働。§43/§44 を書いた時点で**この節だけ記録が漏れていた**ので backfill する。

※ ラベルの注意: §42 の「次」では **A2 = TT 画像生成**と予告していたが、実際には A1 の本番運用で出た
OOM とフォントの問題への対処が先行した。ここでは慣用に合わせその後続作業を A2 と呼ぶ。
**TT 画像の API 化(§36 バケツ②)は未着手**で、段階B のスライス 2 で回収する(§44)。

### 段階A1: read API に生成トリガーを追加(2026-07-16)
- `services/generation_service.py` を新設。DB から引数を組んで既存の生成関数を「呼ぶだけ」の gather 層で、
  **streamlit を一切 import しない**(罠39 の版数非両立を踏むため。機械証明テストあり)。
- `GET /api/projects/{id}/summary-text`(告知テキスト)/ `GET /api/projects/{id}/grid-image`
  (アー写グリッド画像・PNG 透過)の 2 本を A0 の /api に追加。read + generate のみで DB/Storage への書き込みは無し。
- コミット: `0a2b9d1`(gather 新設)/ `34c99a9`(エンドポイント)/ `9aa9c2b`(TestClient + import 機械確認)。

### 段階A2: grid 画像の OOM 対策(2026-07-17〜18)
Railway のメモリ上限に対して full-res 合成が重すぎたため、**出力画像の parity を保ったまま**ピークを削った。
macOS 実測で **982MB → 673MB**。
- `003f7a6`: 取得時に元アー写を**最長辺 1200px へ downscale-on-load**(縮小のみ・アスペクト比維持なので
  手動クロップ座標の補正不要)。
- `2ccb19a`: 巨大 JPEG を **draft デコード**してフル解像度復号自体を回避。
- `1fef1fb`: `threading.Lock` で **grid 生成を直列化**(同時 1 件)。複数リクエストでピークが積み上がるのを防ぐ。
  ※ ロックは API 経路のみ。`logic_grid` 自体はロックしないのでアプリ側の単独利用は従来どおり。

### 段階A2: フォント materialize(grid ラベルの日本語化)
- `6a95fe2`: API/Bot 経路は Streamlit view の `ensure_font_available` を通らないため `FONT_DIR` が空のままで、
  `generate_grid_image` が PIL 既定フォントにフォールバック → 日本語ラベルが豆腐(□)になっていた。
  `render_grid_png_for_project` が生成前に `font_service.ensure_font_available` を呼ぶようにして解消。
  grid_font 本体と `resolve_font_path` の最終フォールバック先 `keifont.ttf` の両方を確保する。
- `53dd1ec`: ハードニング。materialize したファイルの**実体検証**(`_is_usable_font` = PIL で開けるか)と、
  **未解決時の警告ログ**を追加。詳細と背景は 罠40。

## 罠40: コミットしただけで push を忘れると、本番はいつまでも古いまま直らない

段階A1(grid 画像の生成トリガー)で入れた**フォント materialize 修正 `6a95fe2`(2026-07-19 13:14 コミット)が
約 6 週間 push されず**、本番 Railway は 1 つ前の `2ccb19a`(同日 12:42 push)のまま動き続けた。
結果、アー写グリッドの日本語ラベルが豆腐(□)のままという症状が延々と再発報告された。
**コードは正しく、原因は 100% デプロイ漏れ**だった。

- 切り分けの決め手は `git reflog show origin/main`。`origin/main` が 2026-07-19 12:42 から動いていないこと、
  修正コミットがその **32 分後**であることが一目で分かる。「直したのに直らない」ときは真っ先にこれを見る。
- 再現も取れる: 本番と同じ `python:3.13-slim` の Docker で旧コミットを走らせると
  `FONT_DIR` は空のまま・`truetype` に実パスが 1 度も渡らず `load_default`(= 豆腐)になり、
  修正後コミットでは `keifont.ttf` が materialize されて日本語グリフが描かれる。
- **教訓**: 修正したら「push した」で終わらせず、**本番の該当デプロイが最新コミットを指しているか**まで確認する。
  Railway が最新を自動デプロイする設定になっているかも併せて確認する。
- ✅ **解決済み(2026-09-01)**: push 後に Railway が再デプロイされ、**本番のアー写グリッドで日本語ラベルが
  正しく表示されることを確認**した。豆腐化は解消。

### 併記の教訓: 画像系のローカル検証は「生成成功」で終えてはいけない
この修正が 6 週間見逃されたもう 1 つの理由は、回帰テストが `ensure_font_available` と `generate_grid_image` を
**両方 monkeypatch していて「呼ばれたこと」しか見ていなかった**こと。例外が出ないことは、
日本語が描けたことを何ひとつ保証しない。

- 見るべきは **`font_exists=True` / `resolve_font_path` の戻りが実パス(`keifont.ttf`)/ `load_default` に
  落ちていない / グリフのマスクが非ゼロ** まで。なお `load_default()` は内部で `truetype(BytesIO)` を呼ぶので、
  「`truetype` が呼ばれた回数」を成功指標にすると**豆腐でも PASS する**。
  **実ファイルパスでの呼び出しだけを数える**こと。
- 対処として `font_service.ensure_font_available` に **materialize したファイルの実体検証**
  (`_is_usable_font` = PIL で開けるか)を入れ、200 応答でも中身がフォントでなければ削除して取り直すようにした。
  旧実装は `size > 0` だけを見ていたため、一度壊れたファイルを掴むと `"cached"` が固着して
  **コンテナが生きている限り自己修復しなかった**。あわせて**未解決時の警告ログ**
  (「PIL 既定フォントにフォールバックする = 日本語ラベルが豆腐になる」)を
  `render_grid_png_for_project` に追加した(`53dd1ec`)。

---

## 46. 段階B スライス1(TT画像API)/ スライス2(flyer画像API)= 完了・本番稼働(2026-09-01〜2026-09-03)

§44 の段階B設計に沿って、Bot が返す2枚(フライヤー / タイムテーブル)を API から生成できるようにした。
すべて generation_service(streamlit 非 import・§45)に載せ、出力は既存アプリと byte parity。

### スライス1: TT 画像 API(§36 バケツ②の回収)
- `25dc7ff`: logic_timetable の streamlit を optional 化(`try: import streamlit / except: st=None`)、
  `st.toast` / `st.error` をガード。描画ロジックは無変更。
- `570563f`: rows から生成用 gen_list を組む純関数 `build_tt_gen_list_from_rows`
  (OPEN/START + タイムテーブル非表示を除外)。
- `61e4558` / `992472e`: `render_timetable_png_for_project` + `GET /api/projects/{id}/timetable-image`。
- `213a452`: 回帰網(エンドポイント + フォント materialize / 豆腐警告)。
- `5b4ef9d`(B-1.5・OOM 対策): アー写を取得直後に描画先サイズへ `ImageOps.fit`。TT は描画先が横長で
  フル解像度を保持する意味がないため、grid の「最長辺一律縮小」ではなく fit が正解。実測ピーク
  id=12 648→440MB / id=13 993→563MB。fit は冪等なので描画側は無変更=parity。

### スライス2: flyer 画像 API(flyer_json 動的キーが最大の論点だった)
- `7cb7830`: grid/TT 生成を PIL 返しヘルパに分離(PNG 版は薄いラッパ・出力不変)。
  flyer が main_source に中間画像(grid or TT)を必要とするため。
- `1d051c3`: `build_flyer_kwargs_for_project`。flyer_json の動的キー(~103)は
  `models/flyer_keys.py` の `FLYER_KEY_REGISTRY` を SSOT にして
  `{e.short_key: flyer_json.get(e.short_key, e.default) for e in REGISTRY}` で一括構築。
  → 「動的キー30+」問題はレジストリ化で解消。
- `c70b9a8`: `render_flyer_png_for_project(project_id, variant)`。`_render_lock` を **RLock 化**
  (flyer が内側で grid/TT 生成ロックを再入するため)。main_source は合成後すぐ解放して gc。
- `63bc0c3`: `GET /api/projects/{id}/flyer-image?variant=grid|tt`。
- OOM 実測(Railway **Hobby**): 最悪 id=13 flyer-grid 851.8MB(1GB 内)。本番疎通で grid/tt とも
  200・約2.0MB・目視OK。**フライヤー画像 API 本番動作確定(2026-09-03)**。

---

## 47. §5 素材取得失敗の「握り潰し」解消(ログ + failures + X-Missing-Assets ヘッダ)(2026-09-03)

段階B の Bot 会話フロー(アー写差し替え→再生成)前の安全弁。アー写・flyer 背景/ロゴの取得が失敗しても
無言で None を返し「素材欠け」で描画継続していた穴(誰も気づけない)を塞いだ。
5コミット: `4ee63f5`(TT)/ `92dcd58`(grid)/ `d2ecd35`(flyer bg/logo)/ `88299ce`(サービス集約)/
`7c4e46d`(API ヘッダ)。各コミット単体で verify 緑・全146 passed。

### 設計(B案採用・合意済み)
- 公開ジェネレータに**任意 out-param `failures: Optional[list]=None`** を追加するのみ。`None`(views 経路)なら
  挙動・出力 byte parity。list を渡したときだけ `{"kind","name","url","reason"}` を append。
- **失敗集約は必ずメインスレッド**。TT/grid prefetch は ThreadPoolExecutor で、worker 内は
  `logging.warning` のみ。構造化エントリは全 future 解決後に `name_to_url`(取得を試みた対象)×
  `image_cache`(結果 None)を突合して作る。
  - ★不変条件: **contextvars でスレッド跨ぎ収集をしない**(executor worker に伝播しないため)。コードにも明記。
- 「空 URL / 画像未設定 = 正常な None」は失敗に数えない・ログも出さない。数えるのは
  「非空なのに status!=200 / 例外 / デコード失敗」だけ。
- flyer は inner render(アー写)の failures 収集を **`main_img is None` の早期 return より前**に行い、
  bg/logo は `create_flyer_image_shadow(failures=...)` へ伝播して合算。
- 二重計上なし: `generate_timetable_image` は `draw_one_row` に `image_cache` は渡すが `failures` は渡さない。
  draw_one_row 側の収集は「image_cache=None の旧/外部経路」専用で dedup ガード付き。

### API サーフェス(B-3 = Bot 会話フローへの橋渡し)
画像 3 エンドポイントは body が PNG のままなので、失敗リストは**レスポンスヘッダ**で返す:
- `X-Missing-Assets-Count`: 件数。**0 でも必ず付ける**(ヘッダ無し=古いデプロイ、と B-3 側で区別するため)。
- `X-Missing-Assets`: `json → UTF-8 → base64`。**HTTP ヘッダは latin-1 しか安全に運べず、日本語アー写名を
  生 JSON で入れると UnicodeEncodeError になる**ため base64 必須。`"手羽先センセーション"` の往復復元を回帰網で固定。
- 404 は Response 構築前に raise = ヘッダ無し(従来どおり)。

### 検証
- RED→GREEN: `requests.get` を 404/例外に monkeypatch し、None 返却 + failures 1件 + WARNING(caplog)を確認。
  空 URL は failures 空・WARNING 無し。
- parity: `failures=None` の出力 byte が変更前と一致(id=12/39 の grid/tt で sha256 一致)。streamlit-free ガード緑。
- ★教訓: parity 検証中に**まさに §5 対象の取得失敗が一過性に発生**し、触っていない grid のハッシュがズレた
  (再実行で一致)。握り潰しがあると parity 検証すら信用できない、という実例。今後は WARNING で即検知できる。
- 補足: `utils/flyer_generator.load_image` の `print(...)` を module logger 化(Railway で追える・挙動不変)。
  リトライ(C案)は不採用。

## 48. 段階B スライス3(LINE Bot 会話フロー)= 実装完了(2026-09-04)

✅ グループ LINE から「アー写差し替え → 対象イベント選択 → フライヤー 2 枚を再生成して返信」までを実装。
アー写更新の中核(B4・§40/§41)は無改造で流用し、その後段だけを足した。
コミット 5 本(C1〜C5)。**実機テストは谷内さんが本番グループで実施**。

### 会話フロー
- **トリガー1(差し替え)**: `@Bot 〇〇のアー写更新` → 画像送信 → 更新(既存 B4)→
  **続けて**「〇〇が出演する直近イベント」をクイックリプライで最大 4 件提示。0 件なら文言のみ。
- **トリガー2(写真なし)**: `@Bot 〇〇の最新`(合図は `最新` / `再生成`)→ 写真を待たず即イベント提示。
- **選択後(postback)**: フライヤー(grid)+ フライヤー(tt)を生成 → Storage 経由で 2 枚返信。
  素材取得失敗(§47 の failures)があれば警告テキストを 1 通添える(**2 枚は必ず送る**)。

### 設計判断(不変条件)
- **ガードを変更**: 従来の「送信者が OWNER」ゲートを撤去し、**許可グループ内なら誰でも可**にした。
  代わりに **テキストのトリガーは自ボット宛メンション必須**(`is_self_mentioned`)を維持して誤爆を防ぐ。
  `owner_user_ids` は互換のため残すがゲートには使わない。postback はメンション起動フローの続きなので
  メンションを要求しない(グループ許可リストは通す)。
- **生成はプロセス内直呼び**。Bot と /api は同一 FastAPI プロセス(§42)なので HTTP 自己呼び出しはしない。
  `generation_service.render_flyer_png_for_project(pid, variant, failures=fails)` を直接呼び、
  `fails` を Python の list で受け取る(`X-Missing-Assets` ヘッダは外部クライアント用に温存し、パースしない)。
- **返信は reply(push 不使用)**。push は無料枠が有限、reply は無制限。
- **★重い生成はバックグラウンド daemon thread**。フライヤー 2 枚は grid 生成(〜690MB / 数十秒)を含むため、
  postback は thread を起動して **callback は 200 を即返す**。reply token は約 1 分有効なのでその範囲で返す。
  テキスト/画像の既存フロー(トリガーの起動・イベント列挙)は軽い read なので同期のまま。
- **選択状態はステートレス**。`data="regen|pid=<int>|artist=<name>"` を postback に埋め、サーバに会話状態を増やさない
  (`pending_store` は「テキスト → 画像」の順待ちという既存用途のまま)。data は 300 bytes 上限に合わせて
  **UTF-8 の途中で切らないよう 1 文字ずつ詰めて**丸める。
- **Storage は (pid, variant) 固定キーで上書き**(`generated/{pid}/flyer_{variant}.png`)。生成物が無限に増えない。
  代わりに CDN / LINE のキャッシュを避けるため返す URL に `?t=<epoch>` を付ける。
  `previewImageUrl` には長辺 240px に縮小した PNG を別途アップする(preview は 1MB 目安の制約があるため)。
- **新しい DB 書き込みは足していない**。今回の追加処理は read + 画像生成 + Storage アップロードのみ。

### イベントの並び(合意済み)
`services/event_service.list_recent_events_for_artist(name, limit=4, today=None)`:
**今日以降を event_date 昇順(近い順)で優先 → 足りなければ過去を降順(新しい順)で補完** → 日付未設定は最後。
`today` は注入可能(テストの決定性。PendingStore の now 注入と同思想)。
出演判定は `timetable_repo.find_projects_by_artist_name`(**JOIN + DISTINCT の 1 クエリ**。完全一致 → ilike フォールバック)。
プロジェクトごとに rows を引く N+1 は作らない。

### 検証
- ユニット/結合 53 本(event_service 11 / bot flow 42)。RED→GREEN を機械確認
  (配線前コミット `7c3cfe5` に当てると 20 failed / 22 passed → 配線後 42 passed)。
- `callback` が **postback で 200 を即返す**ことを TestClient で計測(生成を 2 秒に模しても応答 < 1 秒)。
- 実 DB(read-only)疎通: 「これから優先」経路(未来 2 件 → 過去 1 件で補完)と
  「過去のみ」経路(新しい順 4 件)の両方を実データで確認。
- streamlit-free ガード緑・全テスト 199 passed。

### 申し送り
- LINE 実機テスト(グループでのメンション・ボタン・2 枚受信)は未実施。
- `_spawn_regeneration` は fire-and-forget。生成が reply token の有効期限(約 1 分)を超えると返信が落ちる。
  worst ケース(29 組・grid 版)はローカル実測で 851MB / 数十秒なので、**本番で超過するようなら
  push への切り替え**(無料枠と相談)か、先に「生成中です」を返す 2 段返信を検討する。

## 49. B-3.1: アー写差し替えを完全ボタン対話に一本化(2026-09-04)

✅ B-3(§48)の「名前をテキストに直打ち」を廃止し、**メンション + 合図だけで、あとは全部ボタン**にした。
履歴は書き換えず(rebase/amend なし)、§48 のコミットの上に積んでいる。

⚠️ **注意**: 依頼時の前提は「§48 は未 push」だったが、実際には **§48 は 2026-09-04 21:38 に push 済み**
だった(`git reflog show origin/main` で確認)。つまり本番には一度、旧フロー(名前をテキストで打つ版)が
出ている可能性がある。B-3.1 を push すれば上書きされるが、その間に旧フローを試した人がいれば
「〇〇のアー写更新」の書式で動いていたことになる。

### 統一フロー
```
@Bot アー写変更        → 「どのイベントのアー写を差し替えますか?」+ イベントボタン
  → イベント押下       → 「どのアーティストの…?」+ 出演者ボタン
  → アーティスト押下   → 「「〇〇」の新しい画像を送ってください(5分以内)」
  → 画像を送信         → 更新 → そのイベントの 2 枚を生成 → **1 回の reply でまとめて返信**

@Bot フライヤー        → イベントボタン → 押下 → 2 枚を生成して返信(写真は変えない)
```
- 入口の合図: REPLACE = `アー写変更 / アー写差し替え / アー写差替 / アー写更新 / 写真変更 / 写真差し替え / 写真差替`、
  GET = `最新 / フライヤー / 再生成`。どちらでもなければ使い方を返す。
- **アーティスト名をテキストから読む処理は撤去**した(`extract_artist_name` は死コードになったので関数ごと削除、
  対応するテストも撤去)。打ち間違い・表記ゆれで「見つかりません」になる経路自体が無くなる。

### postback data(4 種別・ステートレス)
| data | 意味 |
|---|---|
| `evt\|flow=<replace\|get>\|pid=<int>` | イベント選択 |
| `more_evt\|flow=..\|page=<n>` | イベント次ページ |
| `art\|pid=<int>\|artist=<name>` | アーティスト選択 |
| `more_art\|pid=<int>\|page=<n>` | アーティスト次ページ |

会話の選択状態はサーバに持たない。**`pending_store` は「画像待ち」だけ**で、payload を
名前だけから **`(project_id, artist)`** に拡張した(どのイベント向けかはボタンで確定済みなので、
画像を受けたらそのまま「更新 → その pid の 2 枚生成」まで進める)。
`artist` は可変長なので、300 bytes 上限に対し **UTF-8 の文字単位で丸める**(バイトで切ると日本語が壊れる)。

### ページング
LINE の quick reply は **items ≤ 13**。そこで **1 ページ 12 件 + ページングボタン 1 = 13** に収めた。
`event_service.list_recent_events(limit, page, today)` /
`event_service.list_event_artists(pid, limit, page)` が **(そのページ, has_more)** を返し、
**has_more のときだけ**【さらに前のイベントを表示】【さらに表示】を足す(空ページのボタンを出さない)。
イベントの並びは §48 と同じ `_sort_recent_first`(これから優先 → 過去補完)を共用。
出演者は **タイムテーブル順のまま**で、`OPEN / START` と物販行のみ除外・重複名は先頭のみ。
**「非表示」フラグの行は除外しない**(表示フラグと差し替え可否は別物。差し替えたいことがある)。

### バックグラウンド化の範囲を広げた
§48 では postback の生成だけを thread に逃がしていたが、B-3.1 では
**画像受信(DL → 更新 → 2 枚生成)も thread** にした。ここは合計で分単位になりうるため。
webhook は両方とも 200 を即返す(TestClient で「生成を 2 秒に模しても応答 < 1 秒」を機械確認)。

### 検証
- ユニット/結合 94 本(bot flow 72 / event_service 22)。RED→GREEN を機械確認
  (B-3.1 前 `3179eb3` に当てると 29 failed + 28 errors / 37 passed → 現行 94 passed)。
- 実 DB(read-only)疎通: `list_recent_events` が 21 件を 12 + 9 に分割し has_more が正しく立つこと、
  `list_event_artists(13)` が 29 組を 12/12/5 に分割することを確認。
- 全テスト 234 passed / streamlit-free ガード緑。

### 申し送り
- 不変条件は §48 のまま: 生成は generation_service 直呼び(HTTP 自己呼び出し無し)・reply のみ(push 不使用)・
  **新規 DB 書き込みは無し**(更新は既存 B4 の `update_artist_photo` だけ)。
- **reply token の 1 分制限**は据え置きの懸念。画像受信フローは「DL + 更新 + 2 枚生成」で §48 より長くなるため、
  実機で超えるなら「先に受付テキストを reply → 完成後に push」の 2 段構えを検討する。

## 50. B-4: グループ起動制御(オーナーの「起動」で有効化・Storage JSON 永続化)(2026-09-04)

✅ 静的な許可リスト(`ALLOWED_GROUP_IDS`)によるグループ制限を廃止し、
**「誰でも Bot をグループに追加できるが、デフォルト無効。オーナーが『起動』と送ったグループだけ使える」**
という動的な起動制御に置き換えた。有効化状態は **Supabase Storage の JSON** に永続化する。

### 挙動
| 状況 | 返信 |
|---|---|
| オーナーが「@Bot 起動」(未有効) | 有効化 + 「起動しました。…参加している【全員】が僕を利用可能です。」 |
| 非オーナーが「起動」(未有効) | 「BOTTZからの指示で起動します。BOTTZをこのグループラインへ招待してください。」 |
| 誰かが「起動」(既に有効) | 「すでに起動しています。メンションを付けてご依頼ください。」 |
| 未有効グループでの通常依頼 | 「このグループはまだ起動していません。オーナーが「起動」と送ると…」 |
| **オーナーが退会**(memberLeft) | 無効化 + 「BOTTZがグループラインから退会したので機能を停止します。…」 |
| Bot 自身が退出(leave) | Storage から静かに削除(もう発言できないので通知しない) |
| Bot が追加された(join) | **何もしない**(デフォルト無効。オーナーの「起動」待ち) |

- **起動後は、そのグループの参加者なら誰でも利用できる**(送信者の OWNER ゲートは B-3 で撤去済み)。
- オーナーが再参加しても自動では再有効化しない。再開はオーナーの「起動」。
- **@All は従来どおり無反応**(`isSelf` が立たない)。起動も依頼も反応しないことを回帰テストで固定した。

### 永続化(なぜ Storage の JSON か)
DB スキーマを変えずに、Railway の再デプロイ・再起動をまたいで状態を保つ必要があった。
そこで **Storage 上の 1 ファイル `bot/activated_groups.json`** を SSOT にした。

```json
{"groups": {"<groupId>": {"activated_by": "<userId>", "activated_at": 1757000000}}}
```

**Storage が SSOT、プロセス内メモリはライトスルー・キャッシュ**:
- 初回アクセス時に 1 回だけ読み、以後はメモリを参照(**webhook ごとに Storage を読まない**。回帰テストで固定)
- activate / deactivate は「メモリ更新 + Storage 書き込み」
- webhook とバックグラウンド thread の両方から触るので `threading.Lock` で保護
- **Storage 読み失敗(ファイル未作成の初回を含む)は空集合で起動**しログのみ。
  「起動できない」より「まだ誰も起動していない」状態で動く方が安全
- 書き込み失敗もログのみ。メモリは更新済みなのでプロセスが生きている間は有効
- **判定不能(Storage 障害)のときは「無効」に倒す**。勝手に使えてしまうより安全側

### 撤去したもの
`_passes_group_guard` は **「グループ発かどうか」だけ**に縮めた。`ALLOWED_GROUP_IDS` は
`BotConfig` に残るがゲートには使わない(README / .env.example に「B-4 で未使用」と明記)。
→ 挙動が変わった点: **許可リスト外のグループは「無反応」ではなく「まだ起動していません」を返す**。
   招待された人が次に何をすればよいか分かる方がよいため(テストも新仕様へ書き換えた)。

### 検証
- ユニット/結合: activation ストア 17 本 + 会話フロー 93 本。RED→GREEN を機械確認
  (配線前 `fe614be` に当てると 16 failed / 93 passed → 現行すべて GREEN)。
- Storage は全てモック(実 Supabase Storage には触っていない)。
- callback が memberLeft / leave / join でも 200 を返すことを TestClient で確認。
- 全テスト 272 passed / streamlit-free ガード緑。

### 申し送り
- **`OWNER_USER_IDS` に谷内さんの LINE userId が入っている必要がある**(起動可否の判定に使う)。
- 初回は Storage に `bot/activated_groups.json` が無い状態から始まる(空集合で正常起動する)。
  最初の「起動」で作成される。
- 実機で確認したいのは「起動 → 依頼 → オーナー退会 → 停止 → 再招待 → 再起動」の一連と、
  別グループでの拒否、@All 無反応。

---

## 51. 保存周りのバグ潰しパス: 🔗リンク根絶 + 保存UI統合 + 症状1真因 + フォント張替(2026-09-04〜05)

本番運用で「保存したのに反映されない」3症状の相談 → read-only 診断 → 修正。統一仮説(load 未 seed)は
実測で棄却(seed は正常・保存は既に save_active_project に一本化)され、原因は別だった。

### 症状1(TT列数が web と LINE で食い違う)= バグではなく "生成画像と保存設定の乖離"
- web の TT/フライヤープレビューは **session 内の一時生成画像**(projects_v4 に画像カラムは無い)。列数やフォントを
  変えても画像は自動再生成されず、**「2列の古い画像」と「DB の tt_columns=1」が同居**しうる。flyer タブの合成/DL が
  この古い画像を使うと、DL したフライヤーと DB(= LINE/API が読む正)が食い違う。根治は下記「保存UI統合」。

### 🔗リンクバグ(真のデータ破壊・最優先)= commit 6c690ea / dba2fd3
- views/flyer.py の `flyer_grid_link`/`flyer_tt_link`(models/flyer_keys.py で persist=False・既定True)が、
  **レンダーの度に無条件で `scale_h ← scale_w` を代入**していた。persist=False なので開くたび True に戻り、
  **フライヤータブを開いて何か保存/生成するだけで、scale_h≠scale_w の健全プロジェクトも scale_h が潰れる**。
- 修正: レンダー本体の無条件代入を撤去し、width スライダーと 🔗 チェックボックスの **on_change**(操作時のみ)へ移行。
  `persist=True` 化は既存の link 意図不明のため見送り。
- 被害(監査): scale_h≠scale_w が残っていたのは id=35 のみ。他17件は既に h==w に平坦化済みで**復元不可**。
  id=35 は Bug7 の min 退化15キーも抱えていたが、タイトル空=終了イベントで削除済み。

### 保存UI統合(症状1の根治)= commit 3e49566 / 6109bff / 568db51 / 295dbc0 / c92e16a / d850908
- 各タブの「設定反映/保存して生成」ボタンを全廃 → プロジェクト名直下に **「💾 プロジェクトを保存する」1つ**
  (「複製して編集」をその右へ移動)。保存 = `save_active_project()`(services 無改造)→ **現在タブのプレビューを
  保存後の状態から再生成**。これで web プレビュー=DB=LINE/API が常に一致。**明示保存型は維持**。
- 「現在のタブ」を知るため st.tabs → **遅延描画(st.radio horizontal)**(st.segmented_control は AppTest 非対応
  =罠34 と同種で不採用)。遅延描画は未描画タブの widget state を Streamlit が破棄するため、ラン先頭で
  session_state を自身に再代入する **ピン留め層 `_pin_session_keys()`**(views/workspace.py)を新設。
  - allow: tt_/grid_/flyer_/proj_/overview_/チケット・自由記述の動的キー。
  - deny: ボタン/download_button/file_uploader(代入で例外)、**`tt_editor_`(延命すると data_editor の
    edited_rows 状態機械が壊れる=罠33)**。再代入は try/except で保護。
  - 既知の限界: data_editor のセル編集を**確定せずに**タブ切替すると、その1セルだけ失われる。
- 生成は保存ハンドラ内(+保存後の初回タブ表示)のみ。**レンダー毎には走らせない(罠16 回帰防止・テスト固定)**。

### フォント欠損(症状3)= DB 2行 UPDATE のみ・コード変更なし
- id=5/6 の `flyer_json.fallback_font='瀞ノグリッチゴシックH1.ttf'` が Storage に無く(HTTP 400)既定へ暗黙
  フォールバックしていた。実在の同系 `Torono_H1.ttf` へ張替(rowcount==1・他101キー不変を assert してコミット、
  まっさら FONT_DIR で実グリフ描画まで検証)。旧値は scratch/backup_flyer_json_id5_id6.json に退避。

### 新しい罠
- **罠41: persist=False + 既定True + レンダー毎の無条件代入 = 進行性のデータ破壊。** 「保存値」ではなく
  「毎ラン復活する既定フラグ」に連動して他キーを書き換えると、開いて保存するだけで健全データが壊れ続ける。
  連動代入は必ず on_change(操作時のみ)に置く。
- **罠42: web プレビューは session キャッシュ画像であり、保存設定と乖離しうる。** DL/合成が古いキャッシュを使うと
  「見た/DLした画像」と「DB(= API/LINE の正)」が食い違う。→ 生成を保存の後段に一本化して同一ランで一致を保証。

---

## 52. 段階C(公演概要→たたき台プロジェクト自動生成)設計(2026-09-05 設計・合意)

⏳ 設計のみ・未実装。LINE から記入テンプレを埋めて送ると、プロジェクト作成 + たたき台のフライヤー/TT を返す。

### フロー
1. `@Bot 新規作成` → **記入テンプレ**を返信(公演概要 / 料金 / アー写グリッド出演者1〜30 / TT設定 / 自由記述)。
2. 埋めて返信 → **LLM で寛容にパース**(記入ブレ吸収)→ **抽出結果をエコー確認**(安全弁)→
   - 同日に既存プロジェクトあり → 「上書き保存しますか?」
   - なし → プロジェクト作成 → 「作成しました…」+ 概要テキスト & たたき台フライヤーを返信 → TT設定へ。
3. **たたき台TT**を提示 → 自動編集フォーム(尺変更 / 順入替 / 転換の回数・位置)→ 再計算 → ボタン「保存」「再調整」「取消」。
4. 後日 `@Bot タイムテーブルを調整したい` → イベント選択ボタン → 3 の調整ループ。

### 決定事項
- **権限 = 起動グループ内なら誰でも**(作成も)。安全弁は「日付重複チェック(上書き確認)」+「エコー確認」。
- **LLM = Anthropic API**(`ANTHROPIC_API_KEY` を Railway env に追加)。抽出JSONは DB 書き込み前に検証。将来は
  決定論パーサとのハイブリッドも可。
- **TT engine = 純関数**(初回生成も再調整も同じ関数):
  - 出順 = **グリッド番号の逆**(右下=最大番号が最初 → ①=左上が最後)。
  - 持ち時間 = **一律15分**(既定)。
  - 物販 = 各出番終了の **5分後スタート・60分**。場所 = TT 上から **A→B→C→D→E→A… 循環**(出演行のみ計数)。
  - **転換**(調整時間)= 既存 TT の **「転換」列**を使用。N組ごとに指定分を挿入。
  - TT 列数 = **2列**。
- **未登録アーティスト** = TT 行は名前を**文字列**で持つのでプロジェクトは作れる。写真が引けない枠は
  **黒背景プレースホルダ「メンションを付けてアー写の新規登録を進めてください」**(grid 生成側にコード追加)。
  Artist レコード(写真つき)は別途「新規登録」フローで作る(作成時に空 Artist は作らない)。
- **会話状態は DB に再アンカー**(長時間メモリを持たない):記入テンプレは自己完結、TT調整は既存プロジェクトを
  選び直して DB から読む、保存/取消ボタンは postback に project_id を埋める(ステートレス)。

### スライス案
- C-1: 記入テンプレ送出 + LLM解析 + エコー確認
- C-2: プロジェクト作成 + 日付重複検出 + たたき台フライヤー返信(標準フライヤーレイアウトはここまでに別途決定)
- C-3: TT engine(純関数)+ 初回たたき台TT提示
- C-4: TT自動編集(尺/順/転換)+ 再計算 + 保存/再調整/取消
- C-5: 「タイムテーブルを調整したい」入口(イベント選択→C-4)
- C-6: 新規アーティスト登録 + アー写(黒プレースホルダ連動)

### 未決(実装時に詰める)
- 標準フライヤーのレイアウト / 終演後物販フラグの扱い / 「新規登録」フローの詳細。

---

## 53. 段階C C-1(記入テンプレ送出 + LLM解析 + エコー確認)= 完了・本番稼働(2026-09-05)

✅ LINE で `@Bot 新規作成` → 記入テンプレ返信 → 埋めて返信 → **LLM が構造化抽出 → エコー確認**まで本番で動作確認。
commit `be783a3`(services 新設)/ `46244de`(bot 配線 + anthropic 追加)/ `4fe5733`(確定版テンプレ + プロンプト + ログ強化)/
`752ac86`(tool use 切替)。

### 実装
- `services/event_intake.py`(streamlit-free・`anthropic` 遅延 import):`MSG_INTAKE_TEMPLATE`(谷内さん確定版・
  ■見出し / `→` 区切り / 出演者30枠 / チケット3種 / TT設定 / 自由記述2件)、`SECTION_HEADINGS`(受信判定用)、
  `parse_event_template`(LLM 構造化抽出)、`validate_intake`、`format_intake_echo`。
- bot 配線:メンション付きテキストで「新規作成」→ テンプレ送出 / セクション見出し2つ以上 → 解析フロー(ステートレス・
  pending 不使用)。解析は **daemon thread**(webhook は 200 を即返す)。ガードは起動済みグループ + メンション必須。
- **C-1 は DB 無書き込み**(SessionLocal 非接触を機械証明)。`ANTHROPIC_API_KEY` 未設定でも例外にせず案内文。
- 正規化を LLM プロンプトで指示(`2026/11/03`→`2026-11-03` / `¥6,000`→`6000` / `15分`→`15` / `５組ごと`→`5` /
  `なし`→`False` / `yyyy/mm/dd`・`00:00` 等のプレースホルダは null)。

### ★罠43: Anthropic の構造化出力(厳格スキーマ)は「union型パラメータ ≤16」の制限がある
- `output_config`(effort 指定)や tool use の **strict** は、スキーマを厳格コンパイルし、
  **nullable / anyOf など union 型のパラメータが16個を超えると 400 `invalid_request`**(`too many parameters with
  union types`)で落ちる。記入テンプレの抽出スキーマは nullable 項目が21個あり抵触した(本番で「解析に失敗」の真因)。
- **回避 = tool use(function calling)+ `tool_choice` 強制・strict なし**。厳格コンパイルを通らないので union 数の
  制限を受けず、かつ tool_use.input で構造化 JSON が確実に返る(実 API で抽出正常を確認)。
  - モデル・キー・課金はすべて無罪だった(診断スクリプトで messages.create 単体・models.list は成功していた)。
  - 切り分けは「素の疎通 → output_config → output_config(effort無) → tool use強制 → tool use strict」を1スクリプトで
    全部試して request-id 付きで比較するのが速い。
- 回帰固定:スキーマの union 数が16超であること、`output_config`/`strict` を使わず `tool_choice` 強制であることを
  テストで assert(`test_schema_exceeds_structured_output_union_limit` 等)。

### 申し送り
- モデルは `INTAKE_MODEL = "claude-sonnet-5"`(モジュール定数・1行で差し替え可)。
- 実 API 検証は scratch スクリプト(diag / verify)で行い、後片付け予定。テストは Anthropic をモックし実 API を叩かない。

---

## 54. 段階C C-1.1〜C-2 完了 + 修正パス(#3b/#4/#3a/#3c) + 設計判断確立(2026-09-05〜06)

§53(C-1)以降、段階C を C-1.1〜C-2 まで進め、C-2 実機テストで出た4つの修正ポイントを潰した。
本節は「完了スコープ」「#1〜#4 の対応」「#4 の真因と設計判断」「新しい罠44/45」を正本として記録する。

### 完了スコープ(本番稼働 or push準備完了)
- C-1.1: イベント種別分岐(ガールズ/メンズ)+ 2種の告知フォーマット記入テンプレ。`【イベント種別】` 行で LLM を上書き。
- C-1.2: エコーに TT 既定表示 + イベント名規則(「rock field ULTRA LIVE」は常に名前)+ ワンショット(新規作成+概要 同時送信で解析)。
- C-3: TT engine 純関数 `services/timetable_engine.build_timetable`(逆順・全員一律15分・物販=終演5分後から60分・場所A〜E循環(出演者行のみ)・転換=直前行の adjustment、最後の出演者には付けない)。calculate_timetable_flow を通すゴールデンテスト。
- C-6a: グリッドのアー写未登録枠 = 黒背景プレースホルダ(`logic_grid.create_unregistered_photo_placeholder`)。写真あり経路は SHA256 一致で不変。
- C-2: たたき台プロジェクト作成。`intake_draft_store`(Storage JSON, 32hex, TTL24h)/ `intake_creation.build_draft_from_intake` / 日付重複3択(上書き/別で新規作成/中止)/ 種別確認 / TT画像+グリッド画像を返却。overwrite は flyer_json をマージ(見た目=フライヤーデザインは残す)。
- 主要コミット: C-2 本体 `b118368` / `465a68d`、#3b `66e7ea3`、#4 `369a430`(案1) `62f6f03`(案2)、#3a `1cc29ae`、#3c `dfbe4c7`。

### C-2 実機テストで出た修正ポイント(#1〜#4)と対応
- #2: 生成画像は問題なし(谷内さん確認)。
- #3b: チケット金額を告知文の表記のまま保持(`¥6,000` / `¥2,000` / 当日 `各+¥1,000`)、備考は括弧内だけ(`66e7ea3`)。price を int 化しない、当日の「各+」を備考に移さない。スキーマの price を string 化(union 数は21のまま=罠43 非該当)。エコーの `"%s円"` は撤去(二重化回避)。
- #4: グリッドから登録済み出演者(Luna moon)が欠ける → 真因と設計判断は下記。
- #3a: タイトルとサブタイトルを1行結合『title - subtitle』(`1cc29ae`)。サブタイトル無しは不変。告知テキスト(build_event_summary_text)のみ、フライヤー画像描画は触らない。
- #3c: 出演者の予定組数(例27)を保持(`dfbe4c7`)。正規表現抽出(`_PLANNED_ARTIST_COUNT_RE`, LLM スキーマ非変更=罠43 非該当)→ flyer_json["planned_artist_count"] 保存 → build_event_summary_text に後方互換の Optional 引数。無いときは len にフォールバック(バイト単位不変をゴールデン固定)。
- #1: アーティストにガールズ/メンズ属性を持たせて種別を決定論判定 → C-6b へ延期(スキーマ vs JSON の設計判断が必要)。

### #4 の真因と★設計判断(不変条件)
- 症状: 「Luna moon」がタイムテーブルには写真つきで出るのに、アー写グリッドには黒枠すら出ず完全欠落(6枠しか組まれない)。
- 真因: 「Luna moon」(スペース有り)は artists テーブルに存在しない。登録名は「LunaMoon」(スペース無し, id=266)。過去マージで旧レコードは `Luna moon_merged_<ts>`(id=264)にリネーム。`get_artists_by_names` は完全一致のみで、DB に無い名前を黙って落とす → グリッドに6件しか渡らずセル自体が生成されない。
- TT に出た理由: `logic_timetable` の名前解決が「完全一致 → ダメなら空白除去して ILIKE 部分一致」の2段フォールバックを持つ(L174-179 / L285-289)。grid は完全一致のみ。→ TT と grid の名前解決が不整合だった。
- 対応(案1, `369a430`): 未解決名も枠として残す。`services/artist_service.resolve_artists_in_order` が、入力順の全名前に対し、未解決名へ `ArtistView`(負の一意 id, image_filename=None)をスタンドインとして差し込む → C-6a の黒プレースホルダに合流。両経路(views/grid.py, generation_service)を service 経由に統一。logic_grid は DB クエリを一切持たず負 id の再クエリ落ちが無いことを grep で機械確認。既存描画の不変は SHA256 一致テストで固定。
- 対応(案2, `62f6f03`): 未解決名を §5 failures に `{"kind":"artist_not_registered","name":...}` で積み、`build_failure_notice` で LINE に「◯◯ はアー写未登録です(グリッドでは黒い枠…)」と通知。web にも同趣旨の警告を表示。
- ★設計判断(不変条件): **アプリ層(グリッド/TT の描画)は決定論的な完全一致で名前解決する。名前のゆらぎ解決は前段の LLM(intake)層がユーザー確認付きで行う**(intake なら「Luna moon は LunaMoon のこと?」と人に聞けるため)。谷内さんの判断。→ grid はこの判断どおり完全一致のままにした(曖昧マッチで別グループの写真を誤表示する事故を仕組みで防ぐ)。
- 既知の残課題: TT にはまだ空白除去 ILIKE フォールバックが残存(アプリ層が勝手に曖昧マッチしており上記判断に反する)。**LLM 名寄せ実装後に TT フォールバックを撤去して完全一致へ統一**する。撤去を名寄せより先にやると表記ゆれの写真が一時的に消えるため、順序は「LLM 名寄せ → TT 撤去」。実イベントで実写真を出したいときは概要の表記を登録名(例 `LunaMoon`)に合わせる。

### ★罠44: C-6a の黒プレースホルダは「Artist レコードはあるが写真が無い」枠にしか効かない
Artist レコード自体が引けない(名前不一致など)と、枠そのものが生成されずプレースホルダの出番が無い(=見えない欠落)。名前解決の完全一致漏れは、プレースホルダとは別に「未解決名もセルとして残す(スタンドイン差し込み)」で塞ぐ必要がある。

### ★罠45: get_artists_by_names は DB に無い名前を黙って落とす(既存仕様)
`repositories/artist_repo.py`: `return [by_name[n] for n in names if n in by_name]`。docstring にも「見つからない name は skip」と明記。呼び出し側で「入力順の全名前を保つ」処理をしないと、未登録名が可視化されず欠落する(grid がこれを踏んでいた=#4)。

### #3c 実装メモ(保存先の判断)
- 保存先は flyer_json["planned_artist_count"]。理由: apply_draft が flyer_json だけをマージするため、web から保存しても値が残る。settings_json は全置換なので不可。
- build_event_summary_text は末尾に Optional[int] 引数を追加。None なら現状どおり len(既存不変)。呼び出し元3箇所を配線済み: views/flyer.py:588 / views/overview.py:358 / generation_service.py:141。

### 検証 / 本番反映
- #3b / #4: verify.sh + bot 系フルスイート green。実機(web=7枠+黒枠+警告 / LINE=未登録通知)確認済み・push 済み・本番稼働。
- #3a / #3c: verify.sh 169 / bot 系 478 green。予定数なしの告知テキストはバイト単位不変(ゴールデン固定)。実機テストと push は保留中(この §54 記録と同時に push 予定 = `1cc29ae` / `dfbe4c7` + 本記録)。

### 申し送り(次スライス)
- C-4(TT 自動編集, build_timetable 再利用)/ C-5(調整入口)/ C-6b(新規アー写登録 + 名前タイポチェック + #1 種別属性 + **LLM 名寄せ確認**)/ styled フライヤー標準テンプレ(ガールズ/メンズ)。
- LLM 名寄せが入ったら TT の空白除去フォールバックを撤去し、アプリ層を完全一致に統一。

### 告知テキストの追加修正(Issue1 二重※ / ■■ 二重 / Issue2 予定組数 web入力)= 完了・push準備完了
C-2 実機テストの続きで見つかった、告知テキスト(build_event_summary_text)の整形2件と予定組数の web 入力。
- Issue1 二重※(`1d0f249`): 共通備考が「※※各ドリンク代別」と二重化(保存値が既に ※ 込みなのに表示側でも ※ を付ける)。表示側で先頭 ※(全角/半角スペース含む)を全部剥がしてから ※ を1個だけ付ける。※/空白だけの備考は行ごと落とす。文中の ※ は残す。
- ■■ 二重(`b5b856b`): 自由記述の件名も同型で「■■注意事項」と二重化。ヘルパを `_strip_leading_note_marks` → `_strip_leading_marks(value, mark)` に一般化し ※/■ で共有(片方だけ直る事故を防ぐ)。件名が空になれば孤立■を出さない、件名も本文も空ならブロックごと落とす。
- Issue2 予定組数 web入力(`a62edfd`): 概要タブに「予定組数」入力欄。widget key=flyer_planned_artist_count とし、既存の保存(session→`flyer_*` 総取りの blocklist→apply_draft が flyer_json をマージ)とロード(legacy_adapter が None をスキップ=フォールバック)にそのまま乗せた。専用配線は不要。min_value=1(0と未設定を区別できないため)。空欄=None=実組数フォールバック。`_overview_params()` と render 側で重複していた比較辞書を一本化(永久「未保存」バグの同時修正)。
- UIテストの実データ非依存化(`d40df1e`): AppTest が本番DBの状態を読む作りで、谷内さんのローカル実機テストで本番 id=41 に planned=27 が保存された(=Issue2 の本番動作の証跡)ことで落ちた。テストを保存値に依存しない形へ。
- このパスの未push: 1cc29ae(#3a) / dfbe4c7(#3c) / 1d0f249(Issue1) / a62edfd(Issue2) / d40df1e(UIテスト) / b5b856b(■) + 本 §54 記録。実機テスト(web=※1個・■1個・予定組数27→保存→反映)確認済み。

### ★罠46: ローカル Streamlit も接続先は本番 Supabase / AppTest が生 DB 状態に依存すると落ちる
ローカルで `streamlit run` しても secrets.toml の DB_URL は本番 Supabase を指す。ゆえに「入力→保存」テストは本番DBに書き込まれる(テストは必ず【テスト】名プロジェクトで行う)。また AppTest がアクティブプロジェクト等の生DB状態を読む設計だと、本番データの変化でテストが落ちる。UIテストは保存値に依存しない形に作る(将来はテスト時のDBアクセスを隔離する)。

## フェーズ計画 現在地(2026-09-06 時点)

- **Phase 5(残りビュー移行)= ✅ 完全クローズ(2026-07-14)**: artists / grid(§24〜§28)/
  flyer 全スライス完了。flyer = F-rows(§29)/ F-C(§30)/ F-asset(§31)/ F-proj(§33)/ F-tmpl(§34)/
  F-db(§35)(commit b26c2bc / df26219 / 6858785 / 61ca4ad / e159c46 / 30a98d9、本番反映済み)。
  **flyer ビュー db 全滅。次の主戦場は Phase 6 残り**。
- **別件バグ修正(完了)**: TT エディタ「2回目の編集が消える」を根治(§32、commit 945d422、
  本番反映済み・実機テスト合格)。flyer 移行とは別トラック。回帰網 tests/test_tt_editor_repro.py 追加。
- flyer の論点(Phase 0 で確定予定): flyer_json の動的キー30+、罠18(widget SSOT・
  flyer_date_format の key 無し radio 等)、罠22(別テーブル flyer_templates.data_json との
  切り分け)、write 有無 / read escape / 既存窓口(list_projects_for_selector /
  get_rows_for_project / get_artists_by_names / font_service)で代替可否。
- 既知の制限(§21、保留継続): data_json 旧名 / loser 画像孤児化 /
  過去 merge の grid_order_json 残留の一括修復。いずれも慎重案件。
- テスト基盤: AppTest スモーク導入済み(§23)。flyer 移行時の回帰土台。
- 運用: main 直コミット(§27)。1コミット=1目的、Edit/Write は diff 提示→承認、
  push は谷内さんGO必須、本番データ保護モード厳守。
- **Phase 6(残りリファクタ)= ✅ 完全クローズ(2026-07-14)**: 死コード掃除 / 罠7 撤去(§37)/
  裸 except 撲滅(§38)/ 型ヒント コア公開 API(§39)/ キャッシュ現状維持決定(§39)。
  **→ リファクタ Phase 1〜6 完了。次の主戦場は LINE Bot(§11.7 段階A)**。
- ✅ **LINE Bot B4(アー写更新)本番稼働開始(2026-07-16、§41)**。設計・3大決定は §40、
  デプロイ完遂(Railway / Docker)と派生3罠(罠36〜38)は §41。実機テスト合格・本番 Streamlit 無停止。
- ✅ **bot ドキュメント整合 完了(2026-07-16、94f36ad / 135dc54)**: bot/requirements.txt 先頭コメント +
  bot/README.md(ローカル起動節・Railway 節)を「Docker は root+bot を full install」の実態に整合
  (旧「streamlit 共存不可 / pandas 除外」記述を撤去)。Railway の Custom Start Command 空運用(罠36)も明記。
  ※ この時「streamlit と fastapi は共存可能」と書いたが版数では両立不可が正(§42・罠39 で訂正済み)。
- ✅ **段階A0(read API + API キー認証)完了・本番稼働(2026-07-16、§42)**: bot/main.py に read 専用 /api を
  同居 mount(5 本・DTO JSON 返し)。EVENT_API_KEY 認証(hmac・fail-closed・Webhook 署名と別系統)。
  /api の 500 は streamlit×fastapi 版数非両立(罠39)が根因で、project_service の read 経路を streamlit/session_manager
  非依存化して解消(8af2d69 + 機械証明 aab86b7)。**次アクション = A1(grid 画像・告知テキストの生成トリガー・§36 バケツ①)**。
- ✅ **段階A1(生成トリガー)/ A2(grid 画像の OOM 対策・フォント materialize)= 完了・本番稼働(§45)**。
  記録漏れだった分を §45 に backfill 済み。**TT 画像の API 化(§36 バケツ②)は未着手**で段階B へ回収(§44)。
- ✅ **TT タブ 4 機能(一括追加 / 一括削除 / アー写グリッド表示順 / アー写グリッド非表示)完了
  (2026-09-01、§43)**: 本番反映済み(origin/main = `f2d11ae`)。**非永続フィールド + grid_settings の
  seed/save** パターンを確立し、DB スキーマを変えずに UI 列を増やせるようになった。
  grid の DnD は撤去し、**TT の番号が並び順の唯一の正**。
- ✅ **段階B スライス1(TT画像API)/ スライス2(flyer画像API)= 完了・本番稼働(§46)**。
  generation_service に集約(streamlit 非依存)、出力は byte parity、OOM は Hobby 内(最悪 flyer id=13 852MB)。
  flyer_json の動的キーは `FLYER_KEY_REGISTRY` で解消。
- ✅ **§5 素材取得失敗の握り潰し解消 = 実装・レビュー完了(§47、`4ee63f5`〜`7c4e46d` の5コミット)**。
  ログ + `failures` out-param + `X-Missing-Assets` ヘッダ。メインスレッド集約(contextvars 不使用)・parity 維持。push で本番反映。
- ✅ **段階B スライス3(Bot 会話フロー)= 実装完了(§48、`1bad391`〜 の5コミット)**。
  トリガー1(差し替え)/ トリガー2(最新)→ イベント選択(クイックリプライ・ステートレス postback)→
  フライヤー 2 枚を **バックグラウンド thread** で生成して reply。ガードは「許可グループ内なら誰でも +
  テキストはメンション必須」に変更。生成失敗素材は §47 の failures を **プロセス内で直接受け取り**警告文に。
  **→ 段階B(§44)の 3 スライスすべて実装完了。残るは LINE 実機テストと push。**
- ✅ **B-3.1 完全ボタン対話への一本化 = 実装完了(§49、`724cb01` / `bc07d01`)**。
  名前のテキスト入力を廃止(`extract_artist_name` は死コード撤去)。イベント → アーティスト → 画像 →
  自動 2 枚。ページングは 12 件 + ボタン 1 = 13。画像受信もバックグラウンド化。
- ✅ **B-4 グループ起動制御 = 実装完了(§50、`fe614be` / `ec86329`)**。静的許可リストを廃し、
  オーナーの「起動」で有効化。状態は Storage の JSON に永続化(再デプロイでも保持)。
  オーナー退会で自動停止。`ALLOWED_GROUP_IDS` はゲートから外れた。
- ✅ **段階B(§44-50)/ B-4 起動制御 = すべて本番稼働・実機OK(2026-09-04〜05)**。アー写差し替え→
  フライヤー/TT 2枚返信、起動制御(オーナー「起動」で有効化・@All 無反応・退会で停止)まで実機確認済み。
  reply token の 1 分制限は実測 10〜20 秒で余裕(reply 方式で確定・push 不要)。
- ✅ **保存周りのバグ潰しパス = 完了・本番稼働(§51)**。🔗リンクの scale_h 破壊を根絶し、各タブの保存/生成
  ボタンを **プロジェクト単位の1ボタンに統合**。保存後に保存済み状態からプレビュー再生成 → **web=DB=LINE 一致**
  (症状1 根治)。タブは st.tabs→遅延描画(st.radio)+ ピン留め層。フォント欠損(id=5/6)も Torono_H1 へ張替。
- ✅ **段階C C-1(記入テンプレ + LLM解析 + エコー確認)= 完了・本番稼働(§53、2026-09-05)**。
  Anthropic tool use 方式(罠43 回避)。`ANTHROPIC_API_KEY` は Railway 設定済み。実機で解釈エコーまで確認。
- 🎯 **次アクション = 段階C C-3(TT engine 純関数)→ C-2(プロジェクト作成 + 日付重複検出 + たたき台フライヤー)**。
  C-2 の作成にTT行が要るため、純関数の C-3(逆順・15分・物販・転換・A-E循環)を先に作ると C-2 が楽。
  残り C-4(TT自動編集)/ C-5(調整入口)/ C-6(新規アー写登録 + 黒プレースホルダ)。
- 📋 **残タスク(低優先)**: 🔗リンクで過去に平坦化された17件(scale_h=scale_w・復元不可)は必要時に手直し /
  削除経路が services 非経由(§21)。

- ✅ **解決済み(罠40)**: フォント materialize 修正(`6a95fe2` / `53dd1ec`)を push → Railway 再デプロイ →
  **2026-09-01 に本番のアー写グリッドで日本語ラベル表示を確認**。豆腐化は解消済み。
