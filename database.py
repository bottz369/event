from sqlalchemy import create_engine, Column, Integer, String, Text, Boolean, ForeignKey
from sqlalchemy.orm import sessionmaker, declarative_base, relationship
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
    
    # ★重要: created_at は削除しました (DB側で自動設定されるため)
    
    project = relationship("TimetableProject", back_populates="rows")


class Asset(Base):
    __tablename__ = "assets"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String)
    asset_type = Column(String)
    image_filename = Column(String)
    is_deleted = Column(Boolean, default=False)

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
    if not filename: return None
    if filename.startswith("http"): return filename
    return supabase.storage.from_(BUCKET_NAME).get_public_url(filename)
