import os
import json
from sqlalchemy import create_engine, Column, Integer, String, Text, Boolean
from sqlalchemy.orm import sessionmaker, declarative_base

# データの保存先設定
DATA_DIR = "data"
IMAGE_DIR = os.path.join(DATA_DIR, "images")
DB_PATH = os.path.join(DATA_DIR, "app.db")

os.makedirs(IMAGE_DIR, exist_ok=True)

engine = create_engine(f'sqlite:///{DB_PATH}', echo=False)
Base = declarative_base()
Session = sessionmaker(bind=engine)

# --- テーブル定義 ---

class Artist(Base):
    __tablename__ = 'artists'
    id = Column(Integer, primary_key=True)
    name = Column(String, unique=True, nullable=False)
    image_filename = Column(String, nullable=True)
    is_deleted = Column(Boolean, default=False)

class TimetableProject(Base):
    __tablename__ = 'timetable_projects'
    id = Column(Integer, primary_key=True)
    title = Column(String, nullable=False)
    
    event_date = Column(String, nullable=True)
    venue_name = Column(String, nullable=True)
    open_time = Column(String, default="10:00")
    start_time = Column(String, default="10:30")
    goods_start_offset = Column(Integer, default=5) # 出番終了後の物販開始までの分数
    
    data_json = Column(Text, nullable=False) 
    grid_order_json = Column(Text, nullable=True)

class FavoriteFont(Base):
    __tablename__ = 'favorite_fonts'
    id = Column(Integer, primary_key=True)
    filename = Column(String, unique=True, nullable=False)

def init_db():
    Base.metadata.create_all(engine)

def get_db():
    return Session()