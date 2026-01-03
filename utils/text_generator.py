# utils/text_generator.py
import datetime

def get_day_of_week_jp(dt):
    """日付オブジェクトから日本語の曜日を返す"""
    if not dt: return ""
    w_list = ['(月)', '(火)', '(水)', '(木)', '(金)', '(土)', '(日)']
    return w_list[dt.weekday()]

def get_circled_number(n):
    """数値から丸数字を返す"""
    if 1 <= n <= 20:
        return chr(0x2460 + (n - 1))
    elif 21 <= n <= 35:
        return chr(0x3251 + (n - 21))
    elif 36 <= n <= 50:
        return chr(0x32B1 + (n - 36))
    else:
        return f"({n})"

def build_event_summary_text(
    title, subtitle, date_val, venue, url,
    open_time, start_time,
    tickets, ticket_notes,
    artists, free_texts
):
    """
    イベント概要テキストを構築して返す純粋な関数
    StreamlitやDBの依存を持たせず、渡されたデータだけでテキストを作ります
    """
    date_str = ""
    if date_val:
        # datetime.date型か文字列かで分岐
        if isinstance(date_val, (datetime.date, datetime.datetime)):
            date_str = date_val.strftime("%Y年%m月%d日") + get_day_of_week_jp(date_val)
        else:
            date_str = str(date_val)
    
    # 基本情報
    text = f"【公演概要】\n{date_str}\n『{title}』"
    
    if subtitle:
        text += f"\n～{subtitle}～"
        
    text += f"\n\n■会場: {venue}"
    if url:
        text += f"\n {url}"
    
    # 時間（データがない場合は調整中などが入ってくる前提）
    open_t = open_time if open_time else "※調整中"
    start_t = start_time if start_time else "※調整中"
    text += f"\n\nOPEN▶{open_t}\nSTART▶{start_t}"

    # チケット情報
    text += "\n\n■チケット"
    if tickets:
        for t in tickets:
            # 辞書型かオブジェクトかで柔軟に対応
            if isinstance(t, dict):
                name = t.get("name", "")
                price = t.get("price", "")
                note = t.get("note", "")
            else:
                # 万が一辞書でない場合
                name = str(t)
                price = ""
                note = ""

            line = f"- {name}: {price}"
            if note: line += f" ({note})"
            if name or price: text += "\n" + line
    else:
        text += "\n(情報なし)"

    # 共通備考
    if ticket_notes:
        for note in ticket_notes:
            if note and str(note).strip():
                text += f"\n※{str(note).strip()}"

    # 出演者
    # 重複排除しつつ順序保持
    valid_artists = list(dict.fromkeys(artists)) if artists else []
    if valid_artists:
        text += f"\n\n■出演者（{len(valid_artists)}組予定）"
        for i, artist_name in enumerate(valid_artists, 1):
            c_num = get_circled_number(i)
            text += f"\n{c_num}{artist_name}"

    # 自由記述
    if free_texts:
        for f in free_texts:
            if isinstance(f, dict):
                ft = f.get("title", "")
                fc = f.get("content", "")
                if ft or fc:
                    text += f"\n\n■{ft}\n{fc}"
    
    return text
