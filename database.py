from sqlalchemy import create_engine, Column, Integer, String, Text, Boolean
from sqlalchemy.orm import sessionmaker, declarative_base
from supabase import create_client, Client
import streamlit as st
import os

# --- Supabase設定 (Secretsから読み込み) ---
try:
    # URLの形式補正（postgres:// を postgresql:// に変換）
    raw_db_url = st.secrets["supabase"]["DB_URL"]
    if raw_db_url.startswith("postgres://"):
        raw_db_url = raw_db_url.replace("postgres://", "postgresql://", 1)
    
    DB_URL = raw_db_url
    SUPABASE_URL = st.secrets["supabase"]["URL"]
    SUPABASE_KEY = st.secrets["supabase"]["KEY"]
except Exception:
    st.error("SecretsにSupabaseの設定が見つかりません！")
    st.stop()

# --- データベース接続 (PostgreSQL) ---
# SSL接続を強制する設定
try:
    engine = create_engine(
        DB_URL,
        connect_args={"sslmode": "require"}  # Supabase接続に必須
    )
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base = declarative_base()
except Exception as e:
    st.error(f"データベース接続設定エラー: {e}")
    st.stop()

# --- Supabase Storageクライアント ---
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
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

class TimetableProject(Base):
    __tablename__ = "projects_v4"
    
    id = Column(Integer, primary_key=True, index=True)
    title = Column(String)
    event_date = Column(String)
    venue_name = Column(String)
    venue_url = Column(String)
    
    # 時間関連（文字列 "HH:MM" で管理）
    open_time = Column(String)
    start_time = Column(String)
    goods_start_offset = Column(Integer)
    
    # JSONデータ（Text型で定義し、アプリ側でパースする）
    data_json = Column(Text)       # タイムテーブルデータ
    grid_order_json = Column(Text) # アー写グリッド順序
    
    tickets_json = Column(Text)    # チケット情報
    free_text_json = Column(Text)  # 自由入力欄
    
    # チケット共通備考
    ticket_notes_json = Column(Text)
    
    flyer_json = Column(Text)      # フライヤー設定
    settings_json = Column(Text)   # その他設定

# 素材アーカイブ用テーブル
class Asset(Base):
    __tablename__ = "assets"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String)         # 表示名（例: "メインロゴ_白"）
    asset_type = Column(String)   # "logo" or "background"
    image_filename = Column(String)
    is_deleted = Column(Boolean, default=False)

# お気に入りフォント（複数登録用）
class FavoriteFont(Base):
    __tablename__ = "favorite_fonts"
    id = Column(Integer, primary_key=True, index=True)
    filename = Column(String)

# ★追加: 標準フォント設定（1つだけ保存用）
class SystemFontConfig(Base):
    __tablename__ = "system_font_config"
    id = Column(Integer, primary_key=True, index=True)
    filename = Column(String)

# --- データベース初期化関数 ---
def init_db():
    try:
        # 新しいテーブルがあれば作成されます
        Base.metadata.create_all(bind=engine)
    except Exception as e:
        st.error(f"データベース初期化エラー (接続に失敗しました): {e}")
        st.stop()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# --- 画像処理ヘルパー関数 ---

def upload_image_to_supabase(file_obj, filename):
    """画像をSupabase Storageにアップロードし、ファイル名を返す"""
    try:
        file_bytes = file_obj.getvalue()
        # 拡張子に応じたContent-Typeの設定
        content_type = "image/png"
        lower_name = filename.lower()
        if lower_name.endswith(".jpg") or lower_name.endswith(".jpeg"):
            content_type = "image/jpeg"
        elif lower_name.endswith(".webp"):
            content_type = "image/webp"
        
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
    """ファイル名からSupabaseの公開URLを取得"""
    if not filename:
        return None
    if filename.startswith("http"):
        return filename
    # get_public_url は署名なしの公開URLを返す
    return supabase.storage.from_(BUCKET_NAME).get_public_url(filename)
