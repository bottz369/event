from PIL import Image, ImageDraw, ImageFont, ImageOps
import logging
import math
import os
import requests
from io import BytesIO
from concurrent.futures import ThreadPoolExecutor

# streamlit は Streamlit アプリ / ローカル venv にのみ存在する。Bot 実環境(Railway・
# fastapi のみ / starlette 版数衝突=罠39)では import 不能なため任意化する
# (database.py / services/project_service.py と同一方針)。
# ★streamlit がある環境では st は本物のモジュールになり、トースト/エラー表示は従来と
#   完全に同一。st=None 分岐は streamlit 非存在時(= Bot / API 経路)のみ通る。
#   段階B B-1: TT 画像を API から生成するために追加(描画ロジックは無変更・画像 parity 維持)。
try:
    import streamlit as st
except Exception:
    st = None

logger = logging.getLogger(__name__)

# =========================================================
# §5: 素材(アー写 / 背景 / ロゴ)取得失敗の可観測化
# =========================================================
# 従来は取得失敗を静かに None にして「素材なし」で描画継続していたため、
# どの素材が落ちたか誰にも分からなかった(Bot 経由だと追跡不能)。
#   - ログ: failures 引数の有無に関わらず【常に】WARNING を出す(純粋な可観測性)
#   - failures: 任意 out-param。list を渡したときだけ構造化エントリを append する。
#     None(= 既存 views 経路)のときは今日と完全に同一挙動(parity)。
# エントリ形式:
#   {"kind": "artist_photo"|"flyer_bg"|"flyer_logo",
#    "name": <str|None>, "url": <str|None>, "reason": <str>}
# ★スレッド安全: worker 内では logging のみ(logging はスレッド安全)。
#   構造化エントリの収集は必ずメインスレッドで、全 future 解決後に
#   name_to_url と image_cache を突合して行う(contextvars は executor へ
#   伝播しないので使わない)。
# ★空 URL / 空パス由来の None は失敗ではない(ログも failure も出さない)。
# =========================================================

# ================= 設定エリア =================
# 1mm = 10px の高解像度で設定し、印刷時(300dpi等)に綺麗に出るようにします
CANVAS_HEIGHT = 2400       # 全体の高さ (240mm) 固定
COL1_CANVAS_WIDTH = 2800   # 1列モードの幅 (280mm)
COL2_CANVAS_WIDTH = 3600   # 2列モードの幅 (360mm)
COLUMN_GAP = 120           # 2列モード時の列と列の隙間

COLOR_BG_ALL = (0, 0, 0, 0)        # 背景透過
OVERLAY_OPACITY = 170              # 写真上の黒フィルターの濃さ
COLOR_TEXT = (255, 255, 255, 255)  # 文字色

# ================= ヘルパー関数 =================

def get_font(path, size):
    candidates = [
        path,
        os.path.join("assets", "fonts", "keifont.ttf"),
        "fonts/keifont.ttf",
        "keifont.ttf"
    ]
    for c in candidates:
        if c and os.path.exists(c):
            try: return ImageFont.truetype(c, size)
            except Exception: continue
    return ImageFont.load_default()

def load_image(path_or_url):
    """パス/URL から画像を読む。失敗は None(挙動不変)だが §5 で WARNING を出す。"""
    if not path_or_url: return None  # 空は失敗ではない(ログも出さない)
    try:
        if path_or_url.startswith("http://") or path_or_url.startswith("https://"):
            response = requests.get(path_or_url, timeout=10)
            if response.status_code != 200:
                logger.warning(
                    "image fetch failed: url=%r reason=http_%s",
                    path_or_url, response.status_code,
                )
                return None
            return Image.open(BytesIO(response.content)).convert("RGBA")
        if os.path.exists(path_or_url):
             return Image.open(path_or_url).convert("RGBA")
        logger.warning("image load failed: path=%r reason=not_found", path_or_url)
        return None
    except Exception as e:
        logger.warning(
            "image load failed: src=%r reason=%s: %s",
            path_or_url, type(e).__name__, e,
        )
        return None


# =========================================================
# 段階B B-1.5: OOM 対策(JPEG draft + 取得直後の fit)。
#
# ★座標補正が不要な理由: TT のアー写描画は draw_one_row の
#   ImageOps.fit(img, (row_width, row_height), centering=(0.5, 0.5)) だけで、
#   手動クロップ座標 (crop_scale / crop_x / crop_y) を一切使わない(grid と違う点)。
#   fit は完全に「描画先サイズ基準」なので、元画像側を縮めても構図・位置は動かない。
#
# ★なぜ「最長辺 N px への一様縮小」(grid 方式)ではないか:
#   TT の描画先は 1740x159(2列)〜2800x?(1列)と非常に横長で、元アー写は
#   1000〜2000px 程度。一様縮小では幅の制約に阻まれてほとんど縮まらない
#   (実測: 34MB → 30MB)。実際に使われるのは中央の細い帯だけなので、
#   取得直後に描画先サイズへ fit してしまうのが正解(実測: 34MB → 5.5MB)。
#   → キャッシュ保持量が元画像サイズに依存せず 1 枚あたり一定になる。
#
# ★parity: ImageOps.fit は冪等(fit(fit(x)) == fit(x) を実データで完全一致確認済み)。
#   よって draw_one_row 側は無変更のままで出力が変わらない。差分は draft の
#   DCT スケール由来のみ(scratch/parity_tt_downscale.py で知覚不能レベルを数値化)。
# =========================================================
def _load_and_fit_tt(url, target_w, target_h):
    """URL 取得 → JPEG draft デコード → 描画先サイズへ fit(worker スレッド内)。

    Image.draft は load() より前に呼ぶ必要がある。draft は要求サイズを下回らない
    DCT スケールを選ぶので、巨大 JPEG のフル復号を避けつつ画質は保たれる。
    JPEG 以外では no-op(例外時も従来どおり続行)。
    失敗時 None は従来の load_image と同じ(呼び出し側でアー写なし描画になる)。
    """
    try:
        response = requests.get(url, timeout=10)
        if response.status_code != 200:
            logger.warning(
                "artist photo fetch failed: url=%r reason=http_%s",
                url, response.status_code,
            )
            return None
        im = Image.open(BytesIO(response.content))
        try:
            im.draft("RGB", (target_w, target_h))
        except Exception:
            pass  # draft 非対応(PNG 等)/失敗時はフル復号にフォールバック
        im = im.convert("RGBA")
        # draw_one_row と完全に同じ引数で fit する(ここで縮めても結果は変わらない)。
        return ImageOps.fit(
            im, (int(target_w), int(target_h)),
            method=Image.Resampling.LANCZOS, centering=(0.5, 0.5),
        )
    except Exception as e:
        logger.warning(
            "artist photo load failed: url=%r reason=%s: %s", url, type(e).__name__, e
        )
        return None


# =========================================================
# Phase 3 P2: アー写画像並列取得ヘルパー (TT 用、Grid 側と同型)
# =========================================================
def _prefetch_tt_images(timetable_data, db, target_size=None, failures=None):
    """timetable_data の全行をスキャンして name_str → PIL.Image の dict を返す。
    ThreadPoolExecutor で並列 HTTP 取得。出力画像 (タイムテーブル合成結果) は不変。
    HTTP 取得の wall-clock 時間を短縮するための取得フェーズのみ並列化。

    - Artist 解決: 既存 draw_one_row 内と同じロジック (name 完全一致 → ilike fallback)
    - 物販系 ("OPEN / START" / "開演前物販" / "終演後物販") はスキップ
    - URL 生成 (get_image_url) は直列 (DB を引かない・軽い文字列処理)
    - HTTP 取得は max_workers=8 で並列
    - 失敗時は None を返す (既存 load_image の挙動と同じ)
    - 同名行は同じ画像を共有 (1 回取得で済む)
    - DB 二重引き (prefetch でも draw_one_row 内でも Artist を引く) は今回許容。
      DB N+1 解消は別タスク。
    """
    from database import Artist, get_image_url
    SKIP_NAMES = {"OPEN / START", "開演前物販", "終演後物販"}

    # 1. name_str → url を集める (DBクエリ + URL生成は直列)
    name_to_url = {}
    for row in timetable_data:
        if not row or len(row) < 2:
            continue
        name_str = str(row[1]).strip()
        if not name_str or name_str in SKIP_NAMES:
            continue
        if name_str in name_to_url:
            continue
        artist = db.query(Artist).filter(Artist.name == name_str, Artist.is_deleted == False).first()
        if not artist:
            clean = name_str.replace(" ", "").replace("　", "")
            if clean:
                artist = db.query(Artist).filter(Artist.name.ilike(f"%{clean}%"), Artist.is_deleted == False).first()
        if artist and artist.image_filename:
            url = get_image_url(artist.image_filename)
            if url:
                name_to_url[name_str] = url

    # 2. ThreadPoolExecutor で並列 HTTP 取得
    image_cache = {}
    if name_to_url:
        with ThreadPoolExecutor(max_workers=8) as executor:
            # 段階B B-1.5: 描画先サイズが分かっていれば取得直後に fit まで済ませる(OOM 対策)。
            # target_size=None のときは従来どおりフル解像度で取得する(呼び出し側互換)。
            if target_size is not None:
                _tw, _th = target_size
                future_to_name = {
                    executor.submit(_load_and_fit_tt, url, _tw, _th): name
                    for (name, url) in name_to_url.items()
                }
            else:
                future_to_name = {executor.submit(load_image, url): name for (name, url) in name_to_url.items()}
            for fut in future_to_name:
                name = future_to_name[fut]
                try:
                    image_cache[name] = fut.result()
                except Exception as e:
                    logger.warning(
                        "artist photo worker failed: name=%r url=%r reason=%s: %s",
                        name, name_to_url.get(name), type(e).__name__, e,
                    )
                    image_cache[name] = None

    # §5: 失敗の構造化収集は【メインスレッド】で、全 future 解決後に行う。
    # 「取得を試みた(url があった)のに結果が None」= 失敗。
    # 画像未設定(url が無い)アーティストは name_to_url に入らないので数えない。
    if failures is not None:
        for name, url in name_to_url.items():
            if image_cache.get(name) is None:
                failures.append({
                    "kind": "artist_photo",
                    "name": name,
                    "url": url,
                    "reason": "fetch_failed",
                })

    return image_cache


def draw_centered_text(draw, text, box_x, box_y, box_w, box_h, font_path, max_font_size, align="center"):
    text = str(text).strip()
    if not text: return
    current_font_size = max_font_size
    font = get_font(font_path, current_font_size)
    min_font_size = 15
    while current_font_size > min_font_size:
        bbox = draw.multiline_textbbox((0, 0), text, font=font, spacing=4)
        if (bbox[2]-bbox[0]) <= (box_w - 10) and (bbox[3]-bbox[1]) <= (box_h - 4): break
        current_font_size -= 2
        font = get_font(font_path, current_font_size)

    bbox = draw.multiline_textbbox((0, 0), text, font=font, spacing=4)
    text_w = bbox[2] - bbox[0]
    text_h = bbox[3] - bbox[1]
    final_y = box_y + (box_h - text_h) / 2
    if align == "center": final_x = box_x + (box_w - text_w) / 2
    elif align == "right": final_x = box_x + box_w - text_w
    else: final_x = box_x
    
    # 視認性を高めるためのテキストの影（ドロップシャドウ）
    draw.multiline_text((final_x+2, final_y+2), text, fill=(0,0,0,200), font=font, spacing=4, align=align)
    draw.multiline_text((final_x, final_y), text, fill=COLOR_TEXT, font=font, spacing=4, align=align)

def draw_one_row(draw, canvas, base_x, base_y, row_data, font_path, db, row_width, row_height, columns, image_cache=None, failures=None):
    time_str, name_str = row_data[0], str(row_data[1]).strip()
    goods_time, goods_place = row_data[2], row_data[3]

    # 行の高さに合わせてフォントサイズを動的に計算 (上限・下限を設定)
    font_size_artist = min(80, max(20, int(row_height * 0.45)))
    font_size_time = min(70, max(18, int(row_height * 0.40)))
    font_size_goods = min(50, max(15, int(row_height * 0.35)))

    # 列数に応じたエリア幅と座標の計算
    if columns == 1:
        time_w = int(row_width * 0.15)
        goods_w = int(row_width * 0.25)
        artist_w = row_width - time_w - goods_w - 80 
        
        time_x = 40
        artist_x = time_x + time_w
        goods_x = row_width - goods_w - 40
    else:
        time_w = int(row_width * 0.20)
        goods_w = int(row_width * 0.30)
        artist_w = row_width - time_w - goods_w - 40
        
        time_x = 20
        artist_x = time_x + time_w
        goods_x = row_width - goods_w - 20

    # ---------------------------------------------------------
    # 1. 画像処理 & 透過黒フィルター合成
    # ---------------------------------------------------------
    row_img = Image.new('RGBA', (int(row_width), int(row_height)), (0, 0, 0, 0))
    has_image = False

    if name_str and name_str not in ["OPEN / START", "開演前物販", "終演後物販"]:
        try:
            from database import Artist, get_image_url
            artist = db.query(Artist).filter(Artist.name == name_str, Artist.is_deleted == False).first()
            if not artist:
                clean = name_str.replace(" ", "").replace("　", "")
                if clean: artist = db.query(Artist).filter(Artist.name.ilike(f"%{clean}%"), Artist.is_deleted == False).first()

            if artist and artist.image_filename:
                url = get_image_url(artist.image_filename)
                if url:
                    # Phase 3 P2: 並列取得済みの image_cache から取り出し (image_cache=None のとき従来動作にフォールバック)
                    if image_cache is not None:
                        img = image_cache.get(name_str)
                    else:
                        # image_cache 無しの直列フォールバック経路(外部/旧呼び出し用)。
                        # prefetch を通らないので、ここで失敗を拾う必要がある。
                        img = load_image(url)
                        if img is None and failures is not None:
                            # 同じアーティストが複数行にいても 1 件だけ記録する
                            if not any(f.get("kind") == "artist_photo" and f.get("name") == name_str
                                       for f in failures):
                                failures.append({
                                    "kind": "artist_photo",
                                    "name": name_str,
                                    "url": url,
                                    "reason": "fetch_failed",
                                })
                    if img:
                        img_fitted = ImageOps.fit(img, (int(row_width), int(row_height)), method=Image.Resampling.LANCZOS, centering=(0.5, 0.5))
                        row_img.paste(img_fitted, (0, 0))
                        has_image = True
        except Exception: pass

    if has_image:
        overlay_color = (0, 0, 0, OVERLAY_OPACITY)
    else:
        overlay_color = (40, 40, 40, 230)

    overlay = Image.new('RGBA', (int(row_width), int(row_height)), overlay_color)
    
    # 画像とフィルターを合成してキャンバスに貼り付け
    row_composite = Image.alpha_composite(row_img, overlay)
    canvas.paste(row_composite, (int(base_x), int(base_y)), row_composite)

    # ---------------------------------------------------------
    # 2. テキスト描画
    # ---------------------------------------------------------
    draw_centered_text(draw, time_str, base_x + time_x, base_y, time_w, row_height, font_path, font_size_time, align="left")
    draw_centered_text(draw, name_str, base_x + artist_x, base_y, artist_w, row_height, font_path, font_size_artist, align="center")
    
    goods_info = "-"
    if goods_time:
        if " / " in goods_time:
            g_times = goods_time.split(" / ")
            g_places = goods_place.split(" / ") if goods_place else []
            fmt = []
            for idx, t in enumerate(g_times):
                p = g_places[idx] if idx < len(g_places) else (g_places[-1] if g_places else "")
                fmt.append(f"{t} ({p})" if p else t)
            goods_info = "\n".join(fmt)
        else:
            goods_info = f"{goods_time} ({goods_place})" if goods_place else goods_time
    draw_centered_text(draw, goods_info, base_x + goods_x, base_y, goods_w, row_height, font_path, font_size_goods, align="left")

def generate_timetable_image(timetable_data, font_path=None, columns=2, failures=None):
    if not timetable_data: return Image.new('RGBA', (COL1_CANVAS_WIDTH, CANVAS_HEIGHT), (0,0,0,255))
    
    if st is not None:
        st.toast("画像生成完了！", icon="✅")
    
    from database import SessionLocal
    db = SessionLocal()

    try:
        total_artists = len(timetable_data)
        
        # 安全策: ロジック側でも24組以上は強制2列にする
        if total_artists >= 24:
            columns = 2

        if columns == 1:
            left_data = timetable_data
            right_data = []
            canvas_width = COL1_CANVAS_WIDTH
            rows_in_column = total_artists
        else:
            half_idx = math.ceil(total_artists / 2)
            left_data = timetable_data[:half_idx]
            right_data = timetable_data[half_idx:]
            canvas_width = COL2_CANVAS_WIDTH
            rows_in_column = max(len(left_data), len(right_data))

        if rows_in_column == 0: rows_in_column = 1
        
        # ---------------------------------------------------------
        # ★ 高さの自動調整ロジック
        # ---------------------------------------------------------
        margin_between_rows = 12  # 行と行の間の隙間(px)
        
        # キャンバス全体(2400px)を均等に割る
        slot_height = CANVAS_HEIGHT / rows_in_column
        # 実際に描画する高さは、割り当てられた高さからマージンを引いたもの
        row_height = max(10, int(slot_height - margin_between_rows))

        # キャンバス生成
        canvas = Image.new('RGBA', (canvas_width, CANVAS_HEIGHT), COLOR_BG_ALL)
        draw = ImageDraw.Draw(canvas)

        # 1列あたりの幅を計算
        if columns == 1:
            single_col_width = canvas_width
        else:
            single_col_width = int((canvas_width - COLUMN_GAP) / 2)

        # Phase 3 P2: アー写画像を並列取得 (取得フェーズと加工フェーズの分離)。
        # 段階B B-1.5: 描画先サイズ (single_col_width x row_height) が確定してから
        # 呼ぶように移動し、取得直後にそのサイズへ fit する(OOM 対策)。
        # 全行が同じ row_width / row_height で描かれるので、行ごとに目標が変わることはない。
        image_cache = _prefetch_tt_images(
            timetable_data, db, target_size=(int(single_col_width), int(row_height)),
            failures=failures,
        )

        # --- 左列の描画 ---
        y = margin_between_rows / 2
        for row in left_data:
            draw_one_row(draw, canvas, 0, y, row, font_path, db, single_col_width, row_height, columns, image_cache=image_cache)
            y += slot_height

        # --- 右列の描画 ---
        if columns == 2:
            right_col_start_x = single_col_width + COLUMN_GAP
            y = margin_between_rows / 2 
            for row in right_data:
                draw_one_row(draw, canvas, right_col_start_x, y, row, font_path, db, single_col_width, row_height, columns, image_cache=image_cache)
                y += slot_height
            
        return canvas

    except Exception as e:
        if st is not None:
            st.error(f"エラー: {e}")
        else:
            # API / Bot 経路では画面が無いのでログに出す(黙って赤画像を返さない)。
            logging.getLogger(__name__).error("generate_timetable_image failed: %s", e, exc_info=True)
        # 戻り値は従来どおり赤いダミー画像(呼び出し側の分岐を変えないため)。
        return Image.new('RGBA', (COL1_CANVAS_WIDTH, CANVAS_HEIGHT), (255,0,0,255))
    finally:
        db.close()
