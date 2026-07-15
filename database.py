from sqlalchemy import create_engine, Column, Integer, String, Text, Boolean, Float, ForeignKey, LargeBinary
from sqlalchemy.orm import sessionmaker, declarative_base, relationship
from supabase import create_client, Client
import streamlit as st
import os
import urllib.parse  # URLエンコード用

# --- Supabase設定 (Streamlit secrets または 環境変数から読み込み) ---
# Streamlit 実行時は st.secrets、Bot/CLI(Railway 等・Streamlit ランタイム無し)実行時は
# 環境変数を使う。これにより database/services 層を Streamlit 非依存で import できる(§11.7 段階0)。
def _load_supabase_config():
    # ① Streamlit secrets(アプリ実行時・.streamlit/secrets.toml)
    try:
        sec = st.secrets["supabase"]
        return sec["DB_URL"], sec["URL"], sec["KEY"]
    except Exception:
        pass
    # ② 環境変数(Bot / Railway 実行時)
    db_url = os.environ.get("SUPABASE_DB_URL") or os.environ.get("DB_URL")
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_KEY")
    if db_url and url and key:
        return db_url, url, key
    raise RuntimeError(
        "Supabase 設定が見つかりません。Streamlit の st.secrets['supabase'] か、"
        "環境変数 SUPABASE_DB_URL(または DB_URL) / SUPABASE_URL / SUPABASE_KEY を設定してください。"
    )


raw_db_url, SUPABASE_URL, SUPABASE_KEY = _load_supabase_config()
# URLの形式補正（postgres:// を postgresql:// に変換）
if raw_db_url.startswith("postgres://"):
    raw_db_url = raw_db_url.replace("postgres://", "postgresql://", 1)
DB_URL = raw_db_url

# --- データベース接続 (PostgreSQL) ---
# SSL接続を強制する設定。create_engine は遅延接続(ここでは接続しない)なので
# 例外は基本出ないが、出た場合は Streamlit 非依存のため素の例外として送出する。
engine = create_engine(
    DB_URL,
    connect_args={"sslmode": "require"}  # Supabase接続に必須
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# --- Supabase Storageクライアント ---
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# ★重要: 以前の開発環境とバケット名が同じか確認してください。
BUCKET_NAME = "images" 

IMAGE_DIR = "images" 
os.makedirs(IMAGE_DIR, exist_ok=True)

# --- モデル定義 ---

class Artist(Base):
    __tablename__ = "artists"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, index=True)
    image_filename = Column(String)
    is_deleted = Column(Boolean, default=False)

    # ★追加: 画像位置調整用カラム
    crop_scale = Column(Float, default=1.0) # ズーム倍率
    crop_x = Column(Integer, default=0)     # 横方向オフセット
    crop_y = Column(Integer, default=0)     # 縦方向オフセット

class TimetableProject(Base):
    __tablename__ = "projects_v4"
    
    id = Column(Integer, primary_key=True, index=True)
    title = Column(String)
    subtitle = Column(String)  # ★追加: サブタイトル
    event_date = Column(String)
    venue_name = Column(String)
    venue_url = Column(String)
    
    # 時間関連
    open_time = Column(String)
    start_time = Column(String)
    goods_start_offset = Column(Integer)
    
    # JSONデータ
    data_json = Column(Text)
    grid_order_json = Column(Text)
    tickets_json = Column(Text)
    free_text_json = Column(Text)
    ticket_notes_json = Column(Text)
    flyer_json = Column(Text)
    settings_json = Column(Text)

    # 行データへのリレーション
    rows = relationship("TimetableRow", back_populates="project", cascade="all, delete-orphan")

# タイムテーブル行データ保存用テーブル
class TimetableRow(Base):
    __tablename__ = "timetable_rows"
    
    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects_v4.id"), nullable=False)
    
    sort_order = Column(Integer, nullable=False)
    
    artist_name = Column(String)
    duration = Column(Integer)
    is_post_goods = Column(Boolean, default=False)
    adjustment = Column(Integer)
    
    goods_start_time = Column(String)
    goods_duration = Column(Integer)
    place = Column(String)
    
    add_goods_start_time = Column(String)
    add_goods_duration = Column(Integer, nullable=True)
    add_goods_place = Column(String)

    # ★追加: 行を画像生成時に非表示にするフラグ
    is_hidden = Column(Boolean, default=False)
    
    project = relationship("TimetableProject", back_populates="rows")


class Asset(Base):
    __tablename__ = "assets"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String)
    asset_type = Column(String)
    image_filename = Column(String)
    is_deleted = Column(Boolean, default=False)

# フォントファイル保存用テーブル (バイナリ)
class AssetFile(Base):
    __tablename__ = "asset_files"
    id = Column(Integer, primary_key=True, index=True)
    filename = Column(String, unique=True, index=True)
    file_data = Column(LargeBinary) # バイナリデータ

# ★新規追加: フライヤー設定テンプレート保存用
class FlyerTemplate(Base):
    __tablename__ = "flyer_templates"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, index=True) # テンプレート名
    data_json = Column(Text) # 設定データ(JSON)
    created_at = Column(String) # 作成日時 (文字列)

class FavoriteFont(Base):
    __tablename__ = "favorite_fonts"
    id = Column(Integer, primary_key=True, index=True)
    filename = Column(String)

class SystemFontConfig(Base):
    __tablename__ = "system_font_config"
    id = Column(Integer, primary_key=True, index=True)
    filename = Column(String)

# --- 関数群 ---
def init_db():
    try:
        Base.metadata.create_all(bind=engine)
    except Exception as e:
        st.error(f"データベース初期化エラー: {e}")
        st.stop()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def upload_image_to_supabase(file_obj, filename):
    try:
        file_bytes = file_obj.getvalue()
        content_type = "image/png"
        lower_name = filename.lower()
        if lower_name.endswith(".jpg") or lower_name.endswith(".jpeg"):
            content_type = "image/jpeg"
        elif lower_name.endswith(".webp"):
            content_type = "image/webp"
        
        # ファイル名をURLエンコード等はせず、そのままアップロード
        # (Supabase側で保存される名前とDBの名前を一致させるため)
        res = supabase.storage.from_(BUCKET_NAME).upload(
            path=filename,
            file=file_bytes,
            file_options={"content-type": content_type, "upsert": "true"}
        )
        return filename
    except Exception as e:
        st.error(f"画像アップロードエラー: {e}")
        return None

def get_image_url(filename):
    """
    ファイル名からSupabaseの公開URLを取得する
    日本語ファイル名に対応するためURLエンコードを行う
    """
    if not filename: return None
    
    # 既にURL形式ならそのまま返す
    if filename.startswith("http://") or filename.startswith("https://"):
        return filename
    
    # ローカルファイルがあるかチェック (開発用)
    local_path = os.path.join("assets", "artists", filename)
    if os.path.exists(local_path):
        return local_path
        
    try:
        # 日本語ファイル名などをURLで使用できる形式に変換
        # パス区切り文字 '/' はエンコードしないように safe='/' を指定
        safe_filename = urllib.parse.quote(filename, safe='/')
        
        # Supabase Storageから公開URLを取得
        return supabase.storage.from_(BUCKET_NAME).get_public_url(safe_filename)
    except Exception as e:
        print(f"URL生成エラー: {e}")
        return None
