# テスト(AppTest ヘッドレス・スモーク)

Streamlit `AppTest` による自動スモークテスト。本番 Supabase の **read-only ユーザー
(`event_app_readonly`)** に接続し、書き込みは一切行わない。

## 事前準備(初回のみ)

### 1. 開発依存の導入
```bash
python3 -m pip install -r requirements-dev.txt
```
※ DB ドライバ `psycopg2-binary` は本番 `requirements.txt` に含まれるため、
本番と同じ環境なら追加導入は不要。無い場合は `pip install psycopg2-binary`。

### 2. テスト用 read-only secrets の配置(谷内さんが手動)
```bash
cp .streamlit/secrets.readonly.toml.example .streamlit/secrets.readonly.toml
# 実ファイルを開き、DB_URL のユーザーを event_app_readonly にした接続情報等を入力
```
実ファイル `.streamlit/secrets.readonly.toml` は `.gitignore` 済み(コミットされない)。
本番 `.streamlit/secrets.toml` はテストでは一切参照しない。

## 実行

```bash
python3 -m pytest tests/test_smoke_apptest.py -v --disable-warnings
```

全テストまとめて:
```bash
python3 -m pytest -v --disable-warnings
```

## テスト内容

| テスト | 目的 |
|---|---|
| `test_smoke_all_tabs` | 既存プロジェクトを1件選択し、workspace の4タブ(概要/TT/グリッド/フライヤー)が例外なく描画される |
| `test_no_value_bleed_on_switch` | row_counts が異なる既存プロジェクト2件を交互選択し、grid の枚数設定が混入しない(ホットフィックス `7379418` の回帰テスト) |

## 安全設計

- テスト先頭の fixture が `SELECT current_user` を実行し、接続ユーザーが
  `event_app_readonly` でなければ **全テストを即中断**(誤って書き込み可能ユーザーで
  走らせない安全弁)。
- テスト操作は SELECT のみ(プロジェクト選択・タブ描画)。新規作成・保存・
  INSERT/UPDATE/DELETE は行わない(read-only ユーザーで物理的にも不可)。
- `.streamlit/secrets.readonly.toml` の値を Streamlit secrets シングルトンへ直接注入し、
  本番 `secrets.toml` を参照させない。

## スキップされる場合

- `.streamlit/secrets.readonly.toml` 未配置 → 全テスト skip。
- row_counts_str が異なる既存プロジェクトが2件未満 → 該当テスト skip
  (read-only ではテストデータを作れないため、事前に2件用意しておく)。
