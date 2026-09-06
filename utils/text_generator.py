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

def _strip_leading_note_marks(note):
    """共通備考の先頭にある ※ と空白を取り除く(Issue1)。

    告知文から取り込んだ値は「※各ドリンク代別」のように ※ 込みで保存されている
    ことがあり、そのまま出力すると「※※各ドリンク代別」と二重になる。
    保存値に ※ があってもなくても、出力の ※ はちょうど 1 個にそろえる。

    例: "※各ドリンク代別" → "各ドリンク代別"
        "各ドリンク代別"   → "各ドリンク代別"
        "※※ x"           → "x"
    """
    text = str(note).strip()
    while text and (text[0] == "※" or text[0].isspace() or text[0] == "\u3000"):
        text = text[1:]
    return text.strip()


def build_event_summary_text(
    title, subtitle, date_val, venue, url,
    open_time, start_time,
    tickets, ticket_notes,
    artists, free_texts,
    planned_artist_count=None
):
    """
    イベント概要テキストを構築して返す純粋な関数
    StreamlitやDBの依存を持たせず、渡されたデータだけでテキストを作ります

    planned_artist_count (#3c):
        「■出演者（N組予定）」の N に使う「予定組数」。概要に書かれた予定数
        (例 27)を保持しているときだけ渡す。たたき台は一部しか埋まっていない
        ことがあるので、実際に並ぶ名前の数(len)とは別に持てるようにした。
        ★None / 0 / int でない値のときは従来どおり len(valid_artists) を使う。
          渡さなければ出力はバイト単位で従来と同じ(既存プロジェクトは不変)。
    """
    date_str = ""
    if date_val:
        # datetime.date型か文字列かで分岐
        if isinstance(date_val, (datetime.date, datetime.datetime)):
            date_str = date_val.strftime("%Y年%m月%d日") + get_day_of_week_jp(date_val)
        else:
            date_str = str(date_val)
    
    # 基本情報
    # #3a: タイトルとサブタイトルは 1 行にまとめる(『名前 - サブタイトル』)。
    # 旧仕様は『名前』の次行に ～サブタイトル～ を置いていたが、告知文の見出しは
    # 1 行であってほしいという運用判断で共通フォーマットを変更した。
    # サブタイトルが空のときの出力は従来と完全に同じ。
    heading = f"{title} - {subtitle}" if subtitle else title
    text = f"【公演概要】\n{date_str}\n『{heading}』"

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

            # 空行でない場合のみ追加
            if name or price:
                line = f"- {name}"
                if price: line += f": {price}"
                if note: line += f" ({note})"
                text += "\n" + line
    else:
        text += "\n(情報なし)"

    # 共通備考
    # Issue1: 保存値に ※ が含まれていても二重にしない。※ は常にここで 1 つだけ付ける。
    if ticket_notes:
        for note in ticket_notes:
            if note and str(note).strip():
                cleaned = _strip_leading_note_marks(note)
                if cleaned:
                    text += f"\n※{cleaned}"

    # 出演者
    # 安全策: Noneや空文字を除去してから重複排除
    if artists:
        clean_artists = [a for a in artists if a and str(a).strip()]
        valid_artists = list(dict.fromkeys(clean_artists))
    else:
        valid_artists = []

    if valid_artists:
        # #3c: 予定数を保持していればそれを、無ければ実組数を出す。
        # bool は int のサブクラスなので明示的に除く(True が 1 組扱いになるのを防ぐ)。
        if isinstance(planned_artist_count, int) and not isinstance(planned_artist_count, bool) \
                and planned_artist_count > 0:
            shown_count = planned_artist_count
        else:
            shown_count = len(valid_artists)
        text += f"\n\n■出演者（{shown_count}組予定）"
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
