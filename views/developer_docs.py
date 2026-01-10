import streamlit as st

def render_developer_docs_page():
    st.title("🛠️ 開発者向けドキュメント")
    st.caption("本アプリケーションの技術仕様、アーキテクチャ、セットアップ手順書です。")
    st.divider()

    # MDの内容をそのまま記述
    st.markdown("""
    ## 1. プロジェクト概要
    本アプリケーションは、ライブイベント制作における広報素材（タイムテーブル、アー写グリッド、フライヤー、告知テキスト）の生成を自動化する **Streamlit製 Webアプリケーション** です。
    Pythonの画像処理ライブラリ（Pillow）と OpenCV を活用し、DTPソフトのような高度な画像編集をブラウザ上で完結させます。

    ## 2. 技術スタック
    * **Frontend/App**: Streamlit
    * **Language**: Python 3.11+
    * **Database**: **Supabase** (PostgreSQL)
    * **ORM**: SQLAlchemy
    * **Storage**: **Supabase Storage** (画像・フォントの保存)
    * **Image Processing**:
        * **Pillow (PIL)**: 画像合成、テキスト描画、ドロップシャドウ処理
        * **OpenCV (cv2)**: 顔認識によるスマートトリミング
        * **Numpy**: 画像データ変換
    * **PDF Generation**: ReportLab
    * **Coordinates**: `streamlit-image-coordinates` (Click & Move UI)

    ## 3. ディレクトリ構成
    ```text
    event/
    ├── app.py                   # ★エントリーポイント（起動ファイル）
    ├── constants.py             # 定数定義（フォントパス、デフォルト値）
    ├── database.py              # DB接続設定・モデル定義
    ├── requirements.txt         # Python依存ライブラリ
    ├── packages.txt             # OS依存ライブラリ (OpenCV用のlibgl1等)
    │
    ├── data/                    # ローカル一時データ
    │
    ├── logic/                   # 画像生成・データ処理エンジン
    │   ├── logic_grid.py        # アー写グリッド生成・スマートクロップ
    │   ├── logic_timetable.py   # タイムテーブル画像描画
    │   └── logic_project.py     # プロジェクト保存・複製・読込ロジック
    │
    ├── utils/                   # ユーティリティ
    │   ├── __init__.py          # 時間計算、PDF生成、フォント管理の集約
    │   ├── flyer_generator.py   # フライヤー合成・高度な影描画処理
    │   ├── flyer_helpers.py     # 日付変換・フォント同期・画像リサイズ
    │   └── text_generator.py    # 告知テキスト自動生成
    │
    ├── views/                   # UIコンポーネント (Streamlit描画)
    │   ├── workspace.py         # 統合編集画面 (概要/TT/グリッド/フライヤー)
    │   ├── projects.py          # プロジェクト管理
    │   ├── artists.py           # アーティストマスタ管理・トリミングUI
    │   ├── assets.py            # 素材・フォント管理UI
    │   ├── template.py          # テンプレート管理UI
    │   ├── manual.py            # ユーザーマニュアル表示
    │   └── developer_docs.py    # ★開発者ドキュメント表示 (本ファイル)
    │
    └── assets/                  # 静的リソース
    ```

    ## 4. データベース設計 (Schema)
    `database.py` にて定義。ORMには SQLAlchemy を使用しています。

    ### データ保存戦略 (Hybrid Approach)
    本アプリは、**「画面状態の完全保存 (JSON)」** と **「データ検索・再利用 (RDB)」** を両立させるため、以下のハイブリッドな保存方式を採用しています。

    1.  **JSONカラム (`*_json`)**:
        * `projects_v4` テーブルに、各画面の Session State をほぼそのまま JSON 文字列として保存します。これにより、ユーザーが編集していた画面の状態（UIのトグル状態など含む）を完全に復元できます。
    2.  **正規化テーブル (`timetable_rows`)**:
        * タイムテーブルの行データ（出演者、時間、非表示フラグなど）は、別途 `timetable_rows` テーブルにも保存します。これにより、他の機能（アー写グリッドや告知テキスト生成）からデータを参照しやすくしています。

    ### 主なテーブル定義

    | テーブル名 | クラス名 | 役割・特徴 |
    | :--- | :--- | :--- |
    | **projects_v4** | `TimetableProject` | 親テーブル。`data_json` (TT), `grid_order_json`, `flyer_json` 等を持つ。 |
    | **timetable_rows** | `TimetableRow` | 行データ。`sort_order`, `artist_name`, `is_hidden` 等を持つ。 |
    | **artists** | `Artist` | 出演者マスタ。`crop_scale`, `crop_x`, `crop_y` でトリミング情報を保持。 |
    | **assets** | `Asset` | 素材メタデータ（ロゴ・背景・フォント）。 |
    | **flyer_templates** | `FlyerTemplate` | フライヤー設定のテンプレート（JSON保存）。 |

    ## 5. コアロジック解説

    ### A. フォント同期システム (Cloud Compatible)
    * **課題**: RenderやStreamlit Cloudなどのステートレスな環境では、ローカルに置いたフォントファイルがデプロイ時に消えたり、維持されなかったりします。
    * **解決策**: `utils/flyer_helpers.py` の `ensure_font_file_exists` 関数により、必要なフォントがローカルにない場合、**自動的にSupabase Storageからシステム一時フォルダ (`tempfile.gettempdir()`) へダウンロード**します。これにより、どの環境でもカスタムフォントを利用可能です。

    ### B. 画像生成エンジン (`logic/`)
    * **スマートクロップ (`logic_grid.py`)**: OpenCV (`haarcascade_frontalface_default.xml`) を使用して顔認識を行い、自動的に顔を中心としたトリミングを行います。顔が見つからない場合は上部15%を中心とします。
    * **視認性確保 (`logic_timetable.py`)**: タイムテーブル画像では、写真の上に半透明の黒フィルター (`OVERLAY_OPACITY`) を重ね、さらに文字にドロップシャドウをかけることで可読性を担保しています。

    ### C. フライヤーの Click & Move (`views/flyer.py`)
    * `streamlit-image-coordinates` で取得したクリック座標を、プレビュー倍率に基づいて原画（1080px幅）の座標系に変換し、要素の配置 (`pos_x`, `pos_y`) を更新することで直感的なレイアウト調整を実現しています。

    ## 6. セットアップとデプロイ

    ### 必須環境変数 (`.streamlit/secrets.toml`)
    ローカル開発およびデプロイ環境には以下の設定が必要です。

    ```toml
    [supabase]
    URL = "YOUR_SUPABASE_URL"
    KEY = "YOUR_SUPABASE_ANON_KEY"
    DB_URL = "postgresql://user:pass@host:port/db" # postgresql:// に修正済みであること
    ```

    ### 必要なOSパッケージ (`packages.txt`)
    OpenCV を動作させるため、デプロイ先（Render等）で以下のパッケージインストールが必要です。
    ```text
    libgl1-mesa-glx
    libglib2.0-0
    ```
    """)
