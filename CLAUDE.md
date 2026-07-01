# event-app

## 運用ガード(全セッション共通・自動モード含む)

### 絶対に人間承認が必要(自動モードでも勝手に実行しない)
- `git push`(特に `git push origin main`)は必ず人間の最終承認を得てから。本番一発勝負(Streamlit Cloud 自動デプロイ3〜5分)。
- ファイル編集(Edit/Write)は1つずつ diff を見せて承認を得る。「don't ask again」は使わない。

### 本番データ保護(禁止操作)
- DELETE 文 / db.delete() の実行禁止。
- DB スキーマ変更(ALTER TABLE 等)禁止。
- migrate.py の実行禁止。
- 本番 Supabase に対する破壊的操作はすべて禁止。

### investigation-first 原則
- 調査(grep/読み取り)と実装(編集)は分ける。調査フェーズでは ★読むだけ★、ファイルを変更しない。
- 設計変更は谷内さん + Web Claude の合意必須。Claude Code 独自の「改善」は不採用。

### Phase 2B-2-d の境界(現在進行中)
- TT の6状態(tt_artists_order / tt_artist_settings / tt_row_settings /
  tt_has_pre_goods / tt_pre_goods_settings / tt_post_goods_settings)および
  rebuild_table_flag は、-d の実装ステップで初めて削除する。
- それまで(調査フェーズ含む)は ★読むだけ★。session_state からの削除や populate の改変はしない。
