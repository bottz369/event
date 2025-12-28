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
    # ★変更点: テーブル名を変更して新しく作り直します（旧データとの衝突回避）
    __tablename__ = "projects_v2"
    
    id = Column(Integer, primary_key=True, index=True)
    title = Column(String)
    event_date = Column(String)
    venue_name = Column(String)
    
    # ★追加: 会場URL
    venue_url = Column(String)
    
    open_time = Column(String)
    start_time = Column(String)
    goods_start_offset = Column(Integer)
    
    data_json = Column(Text)       # タイムテーブルデータ
    grid_order_json = Column(Text) # アー写グリッド順序
    
    # ★追加: チケット情報と自由入力欄（JSON形式で保存）
    tickets_json = Column(Text)
    free_text_json = Column(Text)

class FavoriteFont(Base):
    __tablename__ = "favorite_fonts"
    id = Column(Integer, primary_key=True, index=True)
    filename = Column(String)

# --- データベース初期化関数 ---
def init_db():
    try:
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
        content_type = "image/png"
        if filename.lower().endswith(".jpg") or filename.lower().endswith(".jpeg"):
            content_type = "image/jpeg"
            
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
