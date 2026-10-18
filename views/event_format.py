"""Optional editor; all writes are to the current draft until unified save."""
from copy import deepcopy
import io

import pandas as pd
import streamlit as st

from models.event_format import KEY, active_parts, new_part, options, schedule, validate, draft_rows
from models.timetable import TimetableRowDraft, draft_rows_to_df, df_to_draft_rows
from services import session_manager


def config():
    draft = session_manager.get_draft_project()
    if draft is None:
        return {}
    cfg = options(draft.settings)
    if not cfg:
        rows = [r.to_legacy_dict() for r in session_manager.get_draft_rows() if not r.is_special_row]
        cfg = dict(enabled=False, count=2, free_viewing=False, free_text="",
                   parts=[new_part(0, draft.open_time, draft.start_time, rows), new_part(1)])
    return cfg


def _put(cfg):
    draft = session_manager.get_draft_project()
    draft.settings = {**draft.settings, KEY: deepcopy(cfg)}
    session_manager.set_draft_project(draft)


def _change(key, field, index=None):
    cfg = config()
    target = cfg if index is None else cfg["parts"][index]
    target[field] = st.session_state[key]
    if field == "enabled" and target[field] and not cfg.get("initialized"):
        draft = session_manager.get_draft_project()
        cfg["parts"][0] = new_part(0, draft.open_time, draft.start_time,
            [r.to_legacy_dict() for r in session_manager.get_draft_rows() if not r.is_special_row])
        cfg["initialized"] = True
    if field == "count":
        while len(cfg["parts"]) < cfg["count"]:
            cfg["parts"].append(new_part(len(cfg["parts"])))
        st.session_state[f"eventfmt_selected_{session_manager.get_active_project_id()}"] = 0
    _put(cfg)




def _field(label, field, index=None, kind="text", **kwargs):
    cfg = config()
    value = (cfg if index is None else cfg["parts"][index]).get(field)
    if kind == "check" and value is None:
        value = False
    key = f"eventfmt_{session_manager.get_active_project_id()}_{index}_{field}"
    if key not in st.session_state:
        st.session_state[key] = "" if kind == "area" and value is None else value
    fn = {"text": st.text_input, "number": st.number_input,
          "check": st.checkbox, "area": st.text_area, "color": st.color_picker}[kind]
    return fn(label, key=key, on_change=_change, args=(key, field, index), **kwargs)


def render_options():
    with st.expander("公演形式・観覧無料の設定"):
        _field("複数部の公演にする", "enabled", kind="check")
        _field("観覧無料を大きく表示する", "free_viewing", kind="check")
        if config().get("free_viewing"):
            _field("観覧無料の補足（場所・条件など）", "free_text")
            _field("観覧無料の下に表示する注意書き（1行に1項目）", "free_notices", kind="area",
                   placeholder="※開場/開演時間は変更になる場合がございます。\n※各部の開場時間前からの場所取りは禁止とさせていただきます。")
            st.caption("VIPなどの有料チケットはイベント概要の料金欄で設定できます。")
        if config().get("enabled"):
            _field("部数", "count", kind="number", min_value=2, max_value=6, step=1)
            st.caption("通常公演のデータはそのまま保持します。部数を減らしても非表示の部は保持されます。")


def _rows_changed(key, index):
    cfg = config()
    base = deepcopy(cfg["parts"][index].get("rows", []))
    for order, row in enumerate(base, 1):
        row["ORDER"] = order
    state = st.session_state.get(key) or {}
    for pos, values in state.get("edited_rows", {}).items():
        base[int(pos)].update(values)
    for pos in sorted(state.get("deleted_rows", []), reverse=True):
        base.pop(int(pos))
    for values in state.get("added_rows", []):
        row = TimetableRowDraft(artist_name="", place="A").to_legacy_dict()
        row.update(values)
        base.append(row)
    base.sort(key=lambda r: float(r.get("ORDER") or 999999))
    converted = df_to_draft_rows(pd.DataFrame(base)) if base else []
    for raw, row in zip(base, converted):
        if raw.get("DURATION") == 0:
            row.duration = 0
        if raw.get("GOODS_DURATION") == 0:
            row.goods_duration = 0
    cfg["parts"][index]["rows"] = [r.to_legacy_dict() for r in converted]
    _put(cfg)
    revision_key = f"eventfmt_revision_{session_manager.get_active_project_id()}_{index}"
    st.session_state[revision_key] = st.session_state.get(revision_key, 0) + 1


def _add_registered(index, key):
    cfg = config()
    rows = cfg["parts"][index]["rows"]
    names = {r.get("ARTIST") for r in rows}
    for name in st.session_state.get(key, []):
        if name not in names:
            rows.append(TimetableRowDraft(artist_name=name, place="A").to_legacy_dict())
            names.add(name)
    _put(cfg)
    st.session_state[key] = []
    rev = f"eventfmt_revision_{session_manager.get_active_project_id()}_{index}"
    st.session_state[rev] = st.session_state.get(rev, 0) + 1


def render_editor():
    from services import font_service
    cfg = config()
    with st.expander("タイムテーブルのデザイン設定"):
        fonts = font_service.list_sorted_fonts()
        font_names = [f["filename"] for f in fonts] or ["keifont.ttf"]
        labels_by_font = {f["filename"]: f["name"] for f in fonts}
        if st.session_state.get("tt_font") not in font_names:
            font_names.append(st.session_state.get("tt_font") or "keifont.ttf")
        st.selectbox("プレビュー用フォント", font_names, key="tt_font",
                     format_func=lambda f: labels_by_font.get(f, f))
        st.radio("各部のタイムテーブル列数", [1, 2], horizontal=True, key="tt_columns")
        st.caption("アー写を背景にした通常版と同じ行デザインを使います。24行以上の部は2列になります。")
    labels = [p["name"] or f"{i + 1}部" for i, p in enumerate(active_parts(cfg))]
    index = st.radio("編集する部", range(len(labels)), format_func=lambda i: labels[i],
                     horizontal=True, key=f"eventfmt_selected_{session_manager.get_active_project_id()}")
    st.subheader(labels[index])
    a, b, c, d = st.columns(4)
    with a:
        _field("部の名前", "name", index)
    with b:
        _field("OPEN（HH:MM）", "open_time", index)
    with c:
        _field("START（HH:MM）", "start_time", index)
    with d:
        _field("部の色", "color", index, kind="color")
    with st.expander("特典会・転換・補足設定"):
        _field("物販開始オフセット（分）", "goods_offset", index, kind="number", min_value=0, step=1)
        _field("生成画像で転換を非表示にする", "hide_transitions", index, kind="check")
        st.caption("非表示でも転換時間は計算に含めます。出演開始時刻は変わりません。")
        _field("転換の表示名（例：VIPエリア入れ替え）", "transition_label", index)
        _field("終演後特典会の準備（分）", "post_prepare", index, kind="number", min_value=0, step=1)
        _field("終演後特典会の開始（空欄なら自動）", "post_start", index)
        _field("終演後特典会の長さ（0なら表示しない）", "post_duration", index, kind="number", min_value=0, step=5)
        _field("補足（公開リハーサル等）", "note", index)
    from services import artist_service
    names = [a.name for a in artist_service.list_artists()]
    add_key = f"eventfmt_add_{session_manager.get_active_project_id()}_{index}"
    st.multiselect("登録済みアーティストから追加", names, key=add_key)
    st.button("選択したアーティストをこの部に追加", key=f"btn_eventfmt_add_{index}",
              on_click=_add_registered, args=(index, add_key))
    part = config()["parts"][index]
    rows = draft_rows(part)
    df = draft_rows_to_df(rows).drop(columns=["DELETE"])
    df.insert(0, "ORDER", list(range(1, len(df) + 1)))
    rev = st.session_state.get(f"eventfmt_revision_{session_manager.get_active_project_id()}_{index}", 0)
    key = f"eventfmt_rows_{session_manager.get_active_project_id()}_{index}_{rev}"
    st.caption("表の下で行を追加できます。「出演順」の番号で並べ替えられます。同じ出演者を別の部にも設定できます。")
    st.data_editor(df, key=key, num_rows="dynamic", height="content", width="stretch",
                   hide_index=False, on_change=_rows_changed, args=(key, index),
                   column_config={
                       "ORDER": st.column_config.NumberColumn("出演順", min_value=1, step=1),
                       "ARTIST": st.column_config.TextColumn("アーティスト", required=True),
                       "DURATION": st.column_config.NumberColumn("出演（分）", min_value=0, step=1),
                       "ADJUSTMENT": st.column_config.NumberColumn("転換（分）", min_value=0, step=1),
                       "IS_POST_GOODS": st.column_config.CheckboxColumn("終演後特典会"),
                       "IS_HIDDEN": st.column_config.CheckboxColumn("TT非表示"),
                       "GRID_HIDDEN": st.column_config.CheckboxColumn("アー写非表示"),
                       "GRID_NO": st.column_config.NumberColumn("アー写順", min_value=1, step=1),
                       "GOODS_START_MANUAL": st.column_config.TextColumn("物販開始（空欄で自動）"),
                       "GOODS_DURATION": st.column_config.NumberColumn("物販分", min_value=0, step=5),
                       "PLACE": "場所", "ADD_GOODS_START": "追加開始",
                       "ADD_GOODS_DURATION": "追加分", "ADD_GOODS_PLACE": "追加場所",
                   })
    errors = validate(config())
    for error in errors:
        st.error(error)
    if not errors:
        calculated, _ = schedule(config()["parts"][index])
        st.dataframe(pd.DataFrame([dict(出演=r["ARTIST"], 開始=r["start"], 終了=r["end"], 特典会=r["goods"])
                                   for r in calculated]), height="content", hide_index=True)


def signature():
    import json
    draft = session_manager.get_draft_project()
    return json.dumps(dict(config=config(), title=draft.title, subtitle=draft.subtitle,
                           event_date=str(draft.event_date), venue=draft.venue_name,
                           tickets=[t.to_dict() for t in draft.tickets],
                           tt_font=st.session_state.get("tt_font"),
                           tt_columns=st.session_state.get("tt_columns"),
                           ticket_notes=draft.ticket_notes, flyer=draft.flyer_settings),
                      ensure_ascii=False, sort_keys=True)


def regenerate():
    from services.event_format_service import render
    draft = session_manager.get_draft_project()
    st.session_state.pop("event_format_preview", None)
    result = {}
    failures = []
    for variant in ("tt", "grid"):
        result[variant] = render(draft, variant, failures=failures)
    st.session_state.last_generated_grid_image = result["grid"]
    st.session_state.last_generated_tt_image = result["tt"]
    from views.flyer import regenerate_flyer_preview
    if not regenerate_flyer_preview(draft.id):
        raise ValueError("フライヤー画像を生成できませんでした。")
    result["flyer_grid"] = st.session_state.flyer_result_grid
    result["flyer_tt"] = st.session_state.flyer_result_tt
    st.session_state.event_format_preview = dict(signature=signature(), images=result)
    if failures:
        st.warning("一部の画像素材を取得できませんでした。未登録のアー写は空枠で表示します。")


def _asset_changed(widget_key, field):
    draft = session_manager.get_draft_project()
    value = st.session_state[widget_key]
    draft.flyer_settings[field] = value
    st.session_state[f"flyer_{field}"] = value
    session_manager.set_draft_project(draft)


def render_style():
    from services import asset_service
    draft = session_manager.get_draft_project()
    for field, category, label in (("bg_id", "background", "背景"), ("logo_id", "logo", "公演ロゴ")):
        assets = asset_service.list_assets_by_type(category)
        labels = {a.id: a.name for a in assets}
        key = f"eventfmt_asset_{draft.id}_{field}"
        choices = [None] + list(labels)
        current = draft.flyer_settings.get(field)
        if current not in choices:
            choices.append(current)
        if key not in st.session_state:
            st.session_state[key] = current
        st.selectbox(label, choices, format_func=lambda v: labels.get(v, "指定なし" if v is None else str(v)),
                     key=key, on_change=_asset_changed, args=(key, field))


def render_preview(tab):
    preview = st.session_state.get("event_format_preview") or {}
    if preview.get("signature") != signature():
        st.info("上の「プロジェクトを保存する」で全体の画像を生成・更新します。")
        return
    variants = ("flyer_grid", "flyer_tt") if "フライヤー" in tab else (("grid",) if "グリッド" in tab else ("tt",))
    for variant in variants:
        image = preview["images"][variant]
        st.image(image, width="stretch")
        buf = io.BytesIO()
        image.save(buf, format="PNG")
        st.download_button("画像をダウンロード", buf.getvalue(), file_name=f"event_{variant}.png",
                           mime="image/png", key=f"dl_eventfmt_{variant}")
