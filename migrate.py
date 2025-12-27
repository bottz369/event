import sqlite3
import os

DB_PATH = os.path.join("data", "app.db")

def migrate():
    if not os.path.exists(DB_PATH):
        print("データベースファイルが見つかりません。app.pyを一度実行して作成してください。")
        return

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    print(f"データベース({DB_PATH})を更新します...")

    # --- artists テーブル ---
    try:
        c.execute("ALTER TABLE artists ADD COLUMN is_deleted BOOLEAN DEFAULT 0")
        print("✅ artists: is_deleted 追加")
    except sqlite3.OperationalError:
        pass

    # --- timetable_projects テーブル ---
    columns_to_add = [
        ("event_date", "TEXT"),
        ("venue_name", "TEXT"),
        ("open_time", "TEXT DEFAULT '10:00'"),
        ("grid_order_json", "TEXT"),
        ("goods_start_offset", "INTEGER DEFAULT 5") # 新規追加: 物販開始までの分数
    ]
    
    for col_name, col_type in columns_to_add:
        try:
            c.execute(f"ALTER TABLE timetable_projects ADD COLUMN {col_name} {col_type}")
            print(f"✅ timetable_projects: {col_name} 追加")
        except sqlite3.OperationalError:
            pass

    # --- favorite_fonts テーブル ---
    c.execute("SELECT count(*) FROM sqlite_master WHERE type='table' AND name='favorite_fonts'")
    if c.fetchone()[0] == 0:
        c.execute("""
            CREATE TABLE favorite_fonts (
                id INTEGER PRIMARY KEY,
                filename VARCHAR NOT NULL UNIQUE
            )
        """)
        print("✅ favorite_fonts テーブル作成")
    
    conn.commit()
    conn.close()
    print("\n🎉 データベース更新完了！")

if __name__ == "__main__":
    migrate()