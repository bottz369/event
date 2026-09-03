"""生成トリガー用サービス(§11.7 段階A1・§36 バケツ①)。

Web API(bot/api.py)から「告知テキスト」「grid 画像」を生成するための、
DB から引数を組む streamlit フリーの gather 層。

不変条件(絶対):
- このモジュールは streamlit を一切 import しない(直下も、辿る先も)。
  views/ や session_manager / project_service(いずれも streamlit を引く)は import しない。
- 既存ロジック関数(utils.text_generator.build_event_summary_text /
  logic_grid.generate_grid_image)は「呼ぶだけ」で中身は変更しない。
- read + generate のみ。DB / Storage への書き込みは行わない。

gather は既存 view(views/flyer.py:490-516 / views/grid.py の設定マッピング)の
導出を「そのまま」DB からに移植したもの。session_state フォールバックは持たない。
"""
from __future__ import annotations

import gc
import io
import json
import os
import threading
from typing import TYPE_CHECKING, List, Optional

if TYPE_CHECKING:  # 型注釈専用(実行時に PIL を import しない)
    from PIL import Image

from constants import FONT_DIR
from database import SessionLocal, get_image_url
from models.flyer_keys import FLYER_KEY_REGISTRY
from logic_grid import generate_grid_image, resolve_font_path
from logic_timetable import generate_timetable_image
from repositories import project_repo
from services import artist_service, asset_service, font_service, timetable_service
from utils.flyer_generator import create_flyer_image_shadow
from utils.flyer_helpers import format_event_date, format_time_str
from utils.logger import get_logger
from utils.text_generator import build_event_summary_text

logger = get_logger(__name__)

# 物販専用行(出演者一覧から除外する。views/flyer.py:506 と同一)
_SPECIAL_ROW_NAMES = ("開演前物販", "終演後物販")

# grid 設定の日本語ラベル → 内部値(views/grid.py:242-244 と同一)
_ALIGN_MAP = {"左揃え": "left", "中央揃え": "center", "右揃え": "right"}
_BRICK_LABEL = "レンガ (サイズ統一)"

# OOM 対策: 画像生成を API 経路で直列化する(同時に1件だけ生成)。
# 複数の生成リクエストが重なって full-res 生成のピークが積み上がるのを防ぐ。
# ※ logic_grid / logic_timetable 自体はロックしない(アプリ側の単独利用は直列化しない)。
#
# ★段階B B-2 で RLock に変更した理由: フライヤー生成は同一スレッド内で
#   grid / TT の生成ヘルパを入れ子で呼ぶ。非再入の Lock のままだと自分自身の
#   ロック待ちでデッドロックする。RLock でも「別スレッドは待たされる」
#   = 同時 1 件という直列化の意味は変わらない。
_render_lock = threading.RLock()


def _loads_list(raw) -> list:
    """JSON 文字列を list として読む。None / 壊れ / 非 list は []。"""
    if not raw:
        return []
    try:
        v = json.loads(raw)
    except Exception:
        return []
    return v if isinstance(v, list) else []


def _loads_dict(raw) -> dict:
    """JSON 文字列を dict として読む。None / 壊れ / 非 dict は {}。"""
    if not raw:
        return {}
    try:
        v = json.loads(raw)
    except Exception:
        return {}
    return v if isinstance(v, dict) else {}


def build_summary_text_for_project(project_id: int) -> Optional[str]:
    """project_id の告知テキストを DB から組んで返す。未検出は None。

    gather(views/flyer.py:490-516 の DB 経路を移植):
      - project は ProjectView(get_project_view 相当)で読む。
      - tickets / ticket_notes / free_texts は tickets_json / ticket_notes_json /
        free_text_json を json.loads した生 list(dict/str)をそのまま渡す
        (build_event_summary_text は isinstance(t, dict) 前提)。
      - open_time / start_time は format_time_str で整形。
      - 出演者名は grid_order_json["order"]、無ければ rows[].artist_name。
        特殊行(開演前/終演後物販)と is_hidden 行を除外。
    """
    db = SessionLocal()
    try:
        view = project_repo.get_project_view(db, project_id)  # ProjectView(frozen・close 後も安全)
    finally:
        db.close()
    if view is None:
        return None

    tickets = _loads_list(view.tickets_json)
    ticket_notes = _loads_list(view.ticket_notes_json)
    free_texts = _loads_list(view.free_text_json)

    rows = timetable_service.get_rows_for_project(project_id)
    hidden_map = {r.artist_name: r.is_hidden for r in rows if r.artist_name}

    raw_order: List[str] = []
    if view.grid_order_json:
        try:
            raw_order = json.loads(view.grid_order_json).get("order", []) or []
        except Exception:
            raw_order = []
    if not raw_order and rows:
        raw_order = [r.artist_name for r in rows]

    filtered_artists: List[str] = []
    for name in raw_order:
        if name in _SPECIAL_ROW_NAMES:
            continue
        if hidden_map.get(name, False):
            continue
        filtered_artists.append(name)

    return build_event_summary_text(
        title=view.title,
        subtitle=view.subtitle,
        date_val=view.event_date,
        venue=view.venue_name,
        url=view.venue_url,
        open_time=format_time_str(view.open_time),
        start_time=format_time_str(view.start_time),
        tickets=tickets,
        ticket_notes=ticket_notes,
        artists=filtered_artists,
        free_texts=free_texts,
    )


def _render_grid_image_for_project(project_id: int) -> Optional["Image.Image"]:
    """project_id の grid 画像を DB 設定から生成し PIL Image で返す。

    段階B B-2: フライヤー合成が main_source に PIL Image を要求するため、
    PNG encode の手前で切り出した内部ヘルパ。PNG bytes が欲しい場合は
    公開版 render_grid_png_for_project() を使う(こちらを呼んで encode するだけ)。

    未検出 project / 出演者ゼロ(generate_grid_image が None)は None。

    gather(views/grid.py の設定マッピングを streamlit フリーに移植):
      - grid_order_json: order(出演者名)/ row_counts_str / layout_mode / alignment
      - settings_json: grid_font(無ければ keifont.ttf)
      - alignment ラベル → left/center/right、layout_mode == "レンガ (サイズ統一)" → is_brick
      - row_counts_str を "," 区切りで int 化(空は None → generate 側で既定 [5]*10)
      - artists は get_artists_by_names(order)。generate_grid_image を直呼び。
    生成物は RGBA 透過なので PNG で bytes 化する(JPEG 不可)。

    OOM 対策: モジュールレベルの _render_lock で全体を囲み、同時に1件だけ生成する。
    """
    with _render_lock:
        db = SessionLocal()
        try:
            proj = project_repo.get_project(db, project_id)  # ORM(settings_json も要るため)
            if proj is None:
                return None
            grid_order_raw = proj.grid_order_json
            settings_raw = proj.settings_json
        finally:
            db.close()

        grid = _loads_dict(grid_order_raw)
        settings = _loads_dict(settings_raw)

        order = grid.get("order") or []
        row_counts_str = grid.get("row_counts_str") or ""
        layout_mode = grid.get("layout_mode")
        alignment_label = grid.get("alignment")

        alignment = _ALIGN_MAP.get(alignment_label, "center")
        is_brick = layout_mode == _BRICK_LABEL
        try:
            row_counts = [int(x.strip()) for x in row_counts_str.split(",") if x.strip()]
        except Exception:
            row_counts = []
        row_counts = row_counts or None  # 空は None → generate_grid_image が既定 [5]*10 を使う

        grid_font = settings.get("grid_font") or "keifont.ttf"
        font_path = os.path.join(FONT_DIR, grid_font)

        artists = artist_service.get_artists_by_names(order)
        if not artists:
            return None

        # フォントを DB から FONT_DIR へ materialize する(Railway 等 API/Bot 経路では
        # Streamlit view の ensure_font_available を通らず FONT_DIR が空のままになり、
        # generate_grid_image が PIL 既定フォントにフォールバック → 日本語ラベルが豆腐化する)。
        # grid_font 本体と、resolve_font_path の最終フォールバック先 "keifont.ttf" の両方を確保。
        # DB read + ローカル一時 FS write のみ(本番 Storage/DB 書き込みは無い)。
        # 失敗しても生成は続行(従来どおりフォールバックで画像自体は出る)。
        for _fname in dict.fromkeys([grid_font, "keifont.ttf"]):
            try:
                _status = font_service.ensure_font_available(_fname)
                logger.info("ensure_font_available(%r) -> %r", _fname, _status)
            except Exception as e:
                logger.warning("ensure_font_available(%r) failed: %s", _fname, e, exc_info=True)

        # materialize の結果を必ずログに残す。generate_grid_image は font 未解決でも
        # 黙って PIL 既定フォント(= 日本語が豆腐)にフォールバックして画像を返すため、
        # ここで警告を出さないと本番で豆腐が出ていることに誰も気づけない
        # (段階A2 のフォント materialize 修正 6a95fe2 が 6 週間見逃された実因。§45/罠40)。
        # 判定は logic_grid と同じ resolve_font_path を使う。
        _resolved = resolve_font_path(font_path) or resolve_font_path("keifont.ttf")
        if _resolved:
            logger.info("grid font resolved: %s", _resolved)
        else:
            try:
                _listing = sorted(os.listdir(FONT_DIR))
            except Exception:
                _listing = None
            logger.warning(
                "grid font NOT resolved (font_path=%r FONT_DIR=%r listing=%r). "
                "generate_grid_image will fall back to the PIL default font and "
                "Japanese labels will render as tofu.",
                font_path, FONT_DIR, _listing,
            )

        img = generate_grid_image(
            artists,
            "",  # image_dir_unused(logic_grid 側で未使用)
            font_path=font_path,
            row_counts=row_counts,
            is_brick_mode=is_brick,
            alignment=alignment,
        )
        return img


def _render_tt_image_for_project(project_id: int) -> Optional["Image.Image"]:
    """project_id のタイムテーブル画像を DB 設定から生成し PIL Image で返す。

    段階B B-2: フライヤー合成が main_source に PIL Image を要求するため、
    PNG encode の手前で切り出した内部ヘルパ。PNG bytes が欲しい場合は
    公開版 render_timetable_png_for_project() を使う。

    未検出 project / 描画対象ゼロ(全行が「タイムテーブル非表示」等)は None。

    gather(views/timetable.py の画像生成ブロックを streamlit フリーに移植):
      - rows は timetable_service.get_rows_for_project(timetable_rows → data_json fallback)
      - open_time / start_time は project_repo.to_draft と同じ正規化を通す
        (アプリの session_state.tt_open_time / tt_start_time と同値)
      - gen_list は timetable_service.build_tt_gen_list_from_rows
        (OPEN / START 行と ★IS_HIDDEN=「タイムテーブル非表示」行を除外)
      - settings_json: tt_font(無ければ keifont.ttf)/ tt_columns(無ければ 2)
      - 24 組以上の強制 2 列は logic_timetable 側にあるのでここでは扱わない
    生成物は RGBA 透過なので PNG で bytes 化する(JPEG 不可)。

    OOM 対策: grid と同じ _render_lock を共有し、同時に 1 件だけ生成する
    (段階B でフライヤーが grid + TT + 合成を連続実行するため、両者を跨いで直列化する)。
    """
    with _render_lock:
        db = SessionLocal()
        try:
            proj = project_repo.get_project(db, project_id)
            if proj is None:
                return None
            draft = project_repo.to_draft(proj)  # open_time / start_time の正規化を再利用
            settings_raw = proj.settings_json
        finally:
            db.close()

        rows = timetable_service.get_rows_for_project(project_id)
        if not rows:
            return None

        settings = _loads_dict(settings_raw)
        tt_font = settings.get("tt_font") or "keifont.ttf"
        try:
            tt_columns = int(settings.get("tt_columns") or 2)
        except Exception:
            tt_columns = 2

        gen_list = timetable_service.build_tt_gen_list_from_rows(
            rows, draft.open_time, draft.start_time
        )
        if not gen_list:
            return None

        # フォントを DB から FONT_DIR へ materialize する(grid と同型・§45 A2)。
        # DB read + ローカル一時 FS write のみ(本番 Storage/DB 書き込みは無い)。
        for _fname in dict.fromkeys([tt_font, "keifont.ttf"]):
            try:
                _status = font_service.ensure_font_available(_fname)
                logger.info("ensure_font_available(%r) -> %r", _fname, _status)
            except Exception as e:
                logger.warning("ensure_font_available(%r) failed: %s", _fname, e, exc_info=True)

        # ★ grid との違い: logic_timetable.get_font の候補は
        #   [渡された path, assets/fonts/keifont.ttf, fonts/keifont.ttf, keifont.ttf] で
        #   **FONT_DIR を見ない**(logic_grid.resolve_font_path とは異なる)。
        #   つまり keifont.ttf を materialize してあっても、渡す path が実在しなければ
        #   PIL 既定フォントに落ちて日本語ラベルが豆腐になる。
        #   そこで service 側で FONT_DIR 内の keifont.ttf へ明示フォールバックする。
        font_path = os.path.join(FONT_DIR, tt_font)
        if not os.path.exists(font_path):
            fallback = os.path.join(FONT_DIR, "keifont.ttf")
            if os.path.exists(fallback):
                logger.warning(
                    "tt font not materialized (%r); falling back to %s", font_path, fallback
                )
                font_path = fallback
            else:
                try:
                    _listing = sorted(os.listdir(FONT_DIR))
                except Exception:
                    _listing = None
                logger.warning(
                    "timetable font NOT resolved (font_path=%r FONT_DIR=%r listing=%r). "
                    "generate_timetable_image will fall back to the PIL default font and "
                    "Japanese labels will render as tofu.",
                    font_path, FONT_DIR, _listing,
                )
        else:
            logger.info("timetable font resolved: %s", font_path)

        return generate_timetable_image(gen_list, font_path=font_path, columns=tt_columns)


# =========================================================
# 公開 API: PNG bytes 版(既存エンドポイントが呼ぶ)
# =========================================================
def _to_png_bytes(img: Optional["Image.Image"]) -> Optional[bytes]:
    """PIL Image を PNG bytes にする。None はそのまま None。

    生成物は RGBA 透過なので PNG で bytes 化する(JPEG 不可)。
    """
    if img is None:
        return None
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def render_grid_png_for_project(project_id: int) -> Optional[bytes]:
    """project_id の grid 画像を PNG bytes で返す。未検出 / 出演者ゼロは None。

    実体は _render_grid_image_for_project。ロックはここで取る
    (ヘルパ側は取らない設計ではなく RLock なので入れ子でも安全)。
    """
    with _render_lock:
        return _to_png_bytes(_render_grid_image_for_project(project_id))


def render_timetable_png_for_project(project_id: int) -> Optional[bytes]:
    """project_id のタイムテーブル画像を PNG bytes で返す。

    未検出 project / 描画対象ゼロ(行なし / 全行が「タイムテーブル非表示」)は None。
    """
    with _render_lock:
        return _to_png_bytes(_render_tt_image_for_project(project_id))


# =========================================================
# 段階B B-2: フライヤー画像
# =========================================================
# 「フライヤーセットの 2 枚」は create_flyer_image_shadow を variant 違いで 2 回呼ぶだけ。
# 差分は main_source(グリッド画像 / TT 画像)と content_scale・pos の 3 キーのみで、
# 他の引数は完全に同一(views/flyer.py:552 _generate_preview)。
_FLYER_VARIANTS = ("grid", "tt")

# styles のうち「フォントファイル名」を持つキー。生成前に実パスへ解決する必要がある
# (views/flyer.py の targets と同一)。
_FLYER_FONT_STYLE_KEYS = (
    "subtitle_font", "date_font", "venue_font",
    "time_font", "ticket_name_font", "ticket_note_font",
)


def build_flyer_kwargs_for_project(project_id: int, variant: str = "grid") -> Optional[dict]:
    """フライヤー生成の引数一式を DB から組む(main_source 以外)。未検出は None。

    views/flyer.py:552 _generate_preview の引数組み立てを streamlit フリーに移植したもの。
    session_state ではなく projects_v4 の各カラム + flyer_json から組む。

    styles:
      FLYER_KEY_REGISTRY(models/flyer_keys.py)が SSOT。persist=True の全キーについて
      flyer_json の値、無ければレジストリの default を採る。create_flyer_image_shadow は
      styles.get(key, default) で読むので欠損には強いが、view と同じ値を渡すためここで埋める。
      フォント名のキーは font_service.ensure_font_path で実パスへ解決する(view と同じ)。

    variant:
      "grid" → content_scale_w/h = grid_scale_w/h、content_pos_y = grid_pos_y
      "tt"   → content_scale_w/h = tt_scale_w/h、  content_pos_y = tt_pos_y
    """
    if variant not in _FLYER_VARIANTS:
        raise ValueError("variant must be one of %r" % (_FLYER_VARIANTS,))

    db = SessionLocal()
    try:
        proj = project_repo.get_project(db, project_id)
        if proj is None:
            return None
        flyer_raw = proj.flyer_json
        subtitle = getattr(proj, "subtitle", "") or ""
        venue_name = proj.venue_name or ""
        event_date = proj.event_date
        open_time_raw = proj.open_time
        start_time_raw = proj.start_time
        tickets_raw = proj.tickets_json
        notes_raw = proj.ticket_notes_json
    finally:
        db.close()

    flyer = _loads_dict(flyer_raw)

    # --- styles: レジストリ駆動で全キーを埋める(欠損は default) ---
    styles = {
        e.short_key: flyer.get(e.short_key, e.default)
        for e in FLYER_KEY_REGISTRY
        if e.persist
    }

    # --- ★view の「🔗 縦横比を固定」の再現(views/flyer.py:366 / 374) ---
    # grid_link / tt_link は FLYER_KEY_REGISTRY で persist=False = DB に保存されない
    # UI 専用フラグで既定 True。view は毎 render で
    #   if st.session_state.flyer_grid_link: st.session_state.flyer_grid_scale_h = new_w
    # を実行するため、リンク ON のときは「高さ % = 幅 %」になる。
    # API にはセッションが無く、常に「アプリを開き直した直後」= リンク ON 相当なので
    # ここで同じ写像を行う。これをしないと、DB に scale_h が別値で残っている
    # プロジェクトでアプリ画面と API 出力が食い違う(実データで検出済み)。
    # ※ DB の scale_h が開くだけで潰れる件はアプリ側の別バグ。ここでは「view と同じ
    #   出力を返す」ことを優先し、挙動を勝手に変えない。
    if flyer.get("grid_link", True):
        styles["grid_scale_h"] = styles.get("grid_scale_w")
    if flyer.get("tt_link", True):
        styles["tt_scale_h"] = styles.get("tt_scale_w")

    # --- variant 差分(view の s_grid / s_tt と同じ 3 キー) ---
    prefix = "grid" if variant == "grid" else "tt"
    styles["content_scale_w"] = styles.get("%s_scale_w" % prefix)
    styles["content_scale_h"] = styles.get("%s_scale_h" % prefix)
    styles["content_pos_y"] = styles.get("%s_pos_y" % prefix)

    # --- 背景 / ロゴ: asset id → AssetView → 公開 URL(view と同じ手順) ---
    def _asset_url(asset_id):
        if not asset_id:
            return None
        view = asset_service.get_asset_view(asset_id)
        return get_image_url(view.image_filename) if view else None

    bg_source = _asset_url(styles.get("bg_id"))
    logo_source = _asset_url(styles.get("logo_id"))

    # --- フォント: 実パスへ解決(view の targets ループと同じ) ---
    for key in _FLYER_FONT_STYLE_KEYS:
        name = styles.get(key)
        if name:
            valid = font_service.ensure_font_path(name)
            if valid:
                styles[key] = valid

    fallback = styles.get("fallback_font") or font_service.get_default_font_name()
    if fallback:
        valid_fb = font_service.ensure_font_path(fallback)
        if valid_fb:
            fallback = valid_fb

    # --- チケット / 共通備考(view と同じく壊れていても落ちない) ---
    tickets = _loads_list(tickets_raw)
    notes = _loads_list(notes_raw)

    return {
        "bg_source": bg_source,
        "logo_source": logo_source,
        "styles": styles,
        "date_text": format_event_date(event_date, styles.get("date_format")),
        "venue_text": venue_name,
        "subtitle_text": subtitle,
        "open_time": format_time_str(open_time_raw),
        "start_time": format_time_str(start_time_raw),
        "ticket_info_list": tickets,
        "common_notes_list": notes,
        "system_fallback_filename": fallback,
    }


def render_flyer_png_for_project(project_id: int, variant: str = "grid") -> Optional[bytes]:
    """project_id のフライヤー画像(PNG)を DB 設定から生成して返す。

    variant="grid" → main_source にアー写グリッド画像、"tt" → タイムテーブル画像。
    未検出 project / main_source を作れない(出演者ゼロ・行ゼロ等)場合は None。

    アプリの「フライヤーセット」2 枚と同じもので、views/flyer.py:552 _generate_preview が
    create_flyer_image_shadow を variant 違いで 2 回呼ぶのを 1 回分ずつ API 化したもの。
    出力は 1080x1350 の RGBA なので PNG で bytes 化する。

    OOM 対策:
      - _render_lock(RLock)で直列化。内側の grid/TT 生成も同じロックを取るが再入可。
      - main_source(grid は 4000x3000 級 / TT は 3600x2400)は合成後すぐ解放して gc する。
        variant ごとに別リクエストなので grid 画像と TT 画像を同時に保持することはない。
    """
    if variant not in _FLYER_VARIANTS:
        raise ValueError("variant must be one of %r" % (_FLYER_VARIANTS,))

    with _render_lock:
        kwargs = build_flyer_kwargs_for_project(project_id, variant=variant)
        if kwargs is None:
            return None

        # フォント materialize(§45 A2 と同型)。styles には ensure_font_path で解決済みの
        # 実パスが入っているが、解決できなかったものはファイル名のまま残るので、
        # ここで DB → FONT_DIR の materialize をもう一度試みる。
        _wanted = []
        for key in _FLYER_FONT_STYLE_KEYS:
            v = kwargs["styles"].get(key)
            if v and not os.path.isabs(str(v)):
                _wanted.append(str(v))
        fb = kwargs.get("system_fallback_filename")
        if fb and not os.path.isabs(str(fb)):
            _wanted.append(str(fb))
        _wanted.append("keifont.ttf")  # create_flyer_image_shadow の最終フォールバック
        for _fname in dict.fromkeys(_wanted):
            try:
                _status = font_service.ensure_font_available(_fname)
                logger.info("ensure_font_available(%r) -> %r", _fname, _status)
            except Exception as e:
                logger.warning("ensure_font_available(%r) failed: %s", _fname, e, exc_info=True)

        # materialize 後にもう一度パス解決を試みる(初回リクエストで DL された分を拾う)。
        for key in _FLYER_FONT_STYLE_KEYS:
            v = kwargs["styles"].get(key)
            if v and not os.path.isabs(str(v)):
                resolved = font_service.ensure_font_path(str(v))
                if resolved:
                    kwargs["styles"][key] = resolved
        if fb and not os.path.isabs(str(fb)):
            resolved_fb = font_service.ensure_font_path(str(fb))
            if resolved_fb:
                kwargs["system_fallback_filename"] = resolved_fb

        # 未解決が残るなら豆腐警告(create_flyer_image_shadow の get_font_path は
        # FONT_DIR を見ないため、実パスでないと PIL 既定フォントに落ちる)。
        _unresolved = [
            key for key in _FLYER_FONT_STYLE_KEYS
            if kwargs["styles"].get(key) and not os.path.exists(str(kwargs["styles"][key]))
        ]
        if _unresolved or (kwargs.get("system_fallback_filename")
                           and not os.path.exists(str(kwargs["system_fallback_filename"]))):
            try:
                _listing = sorted(os.listdir(FONT_DIR))
            except Exception:
                _listing = None
            logger.warning(
                "flyer font(s) NOT resolved (keys=%r fallback=%r FONT_DIR=%r listing=%r). "
                "create_flyer_image_shadow will fall back to the PIL default font and "
                "Japanese text will render as tofu.",
                _unresolved, kwargs.get("system_fallback_filename"), FONT_DIR, _listing,
            )
        else:
            logger.info("flyer fonts resolved (variant=%s)", variant)

        # --- main_source(中間画像)を生成 → 合成 → すぐ解放 ---
        if variant == "grid":
            main_img = _render_grid_image_for_project(project_id)
        else:
            main_img = _render_tt_image_for_project(project_id)
        if main_img is None:
            logger.warning(
                "flyer main_source not available (project=%s variant=%s)", project_id, variant
            )
            return None

        # 生成フェーズの一時確保(アー写バッファ等)を合成前に回収してから合成に入る。
        gc.collect()

        try:
            img, _meta = create_flyer_image_shadow(main_source=main_img, **kwargs)
        finally:
            # 4000x3000 級 RGBA を合成後に抱えたままにしない
            main_img = None
            gc.collect()

        if img is None:
            return None

        png = _to_png_bytes(img)
        img = None
        gc.collect()
        return png
