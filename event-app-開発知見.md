# event-app 開発知見ドキュメント

このファイルはローカル版です。フェーズ計画 / 罠コレクション / バグ履歴の
本体は Web Claude のプロジェクト知識として登録されたメイン版にありますが、
ローカルでも参照できるよう以下のセクションを保存します:
- セクション11: LINE Bot 構想の記録
- セクション12: フェーズ3 パフォーマンス改善の成果記録(2026-06-29)

最終更新: 2026-06-29

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
