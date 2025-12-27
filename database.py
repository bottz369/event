from sqlalchemy import create_engine, Column, Integer, String, Text, Boolean
from sqlalchemy.orm import sessionmaker, declarative_base
from supabase import create_client, Client
import streamlit as st
import os

# --- Supabase設定 (Secretsから読み込み) ---
try:
    DB_URL = st.secrets["supabase"]["DB_URL"]
    SUPABASE_URL = st.secrets["supabase"]["URL"]
    SUPABASE_KEY = st.secrets["supabase"]["KEY"]
except Exception:
    # ローカル開発用などのフォールバック（必要なければエラーにする）
    st.error("SecretsにSupabaseの設定が見つかりません！")
    st.stop()

# --- データベース接続 (PostgreSQL) ---
# SSLモードをrequireに設定（Supabase推奨）
engine = create_engine(DB_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# --- Supabase Storageクライアント ---
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
BUCKET_NAME = "images"  # 作成したバケット名

# 画像の一時保存ディレクトリ（アップロード処理用には使わないが、互換性のため残す）
IMAGE_DIR = "images" 
os.makedirs(IMAGE_DIR, exist_ok=True)

# --- モデル定義 ---
class Artist(Base):
    __tablename__ = "artists"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, index=True)
    image_filename = Column(String)  # Supabase上のファイルパスまたはURL
    is_deleted = Column(Boolean, default=False)

class TimetableProject(Base):
    __tablename__ = "projects"
    id = Column(Integer, primary_key=True, index=True)
    title = Column(String)
    event_date = Column(String)
    venue_name = Column(String)
    open_time = Column(String)
    start_time = Column(String)
    goods_start_offset = Column(Integer)
    data_json = Column(Text)
    grid_order_json = Column(Text)

class FavoriteFont(Base):
    __tablename__ = "favorite_fonts"
    id = Column(Integer, primary_key=True, index=True)
    filename = Column(String)

# --- データベース初期化関数 ---
def init_db():
    Base.metadata.create_all(bind=engine)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# --- 画像処理ヘルパー関数（ここが重要！） ---

def upload_image_to_supabase(file_obj, filename):
    """画像をSupabase Storageにアップロードし、公開URLを返す"""
    try:
        file_bytes = file_obj.getvalue()
        # Content-Typeを推測（簡易的）
        content_type = "image/png"
        if filename.lower().endswith(".jpg") or filename.lower().endswith(".jpeg"):
            content_type = "image/jpeg"
            
        # Storageにアップロード (同名ファイルは上書き設定)
        res = supabase.storage.from_(BUCKET_NAME).upload(
            path=filename,
            file=file_bytes,
            file_options={"content-type": content_type, "upsert": "true"}
        )
        # 公開URLを取得
        public_url = supabase.storage.from_(BUCKET_NAME).get_public_url(filename)
        return filename  # DBにはファイル名を保存し、表示時にURL化する方針
    except Exception as e:
        st.error(f"画像アップロードエラー: {e}")
        return None

def get_image_url(filename):
    """ファイル名からSupabaseの公開URLを取得"""
    if not filename:
        return None
    # 既にhttpで始まるURLならそのまま返す（念のため）
    if filename.startswith("http"):
        return filename
    return supabase.storage.from_(BUCKET_NAME).get_public_url(filename)
