"""タイムテーブル生成エンジン(純関数)。段階C C-3・§52。

出演者と設定から「たたき台のタイムテーブル行」を組み立てる。初回生成(C-2)も
後の再調整(C-4)も同じ関数を呼ぶので、ここが唯一の計算元になる。

設計上の約束:
  - **純関数**。DB も LLM も触らず、streamlit も import しない(罠39)。
    引数だけで出力が決まるので単体テストで完全に固定できる。
  - 返すのは models.TimetableRowDraft のリスト。アプリの行と 1 対 1 で、
    そのまま draft_rows として使える。

★時刻の持ち方(models/timetable.py の設計に合わせる):
  TimetableRowDraft は開始/終了の時刻フィールドを持たない。時計は
  utils.calculate_timetable_flow が start_time から duration / adjustment を
  積み上げて導出する:

      end_time        = current_time + duration
      next_start_time = end_time + adjustment

  つまり **adjustment(転換)は「その行の演奏が終わったあとのすき間」**。
  よって転換は独立した行ではなく、転換の手前に立つ出演者の adjustment に載せる。
  物販開始 (goods_start_time) だけは絶対時刻の文字列なので、ここで計算して入れる。
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import List, Optional, Sequence

from models import TimetableRowDraft

# §52 で合意した既定値。エコーの案内文(services.event_intake.TT_DEFAULTS_NOTICE)と
# 揃えること。
DEFAULT_SET_MINUTES = 15
DEFAULT_CHANGEOVER_EVERY_N = 5
DEFAULT_CHANGEOVER_MINUTES = 5
DEFAULT_GOODS_OFFSET_MINUTES = 5
DEFAULT_GOODS_DURATION_MINUTES = 60
DEFAULT_GOODS_SPACES = ("A", "B", "C", "D", "E")

_TIME_FORMAT = "%H:%M"


def _parse_time(value) -> Optional[datetime]:
    """"HH:MM" を datetime にする。読めなければ None(落とさない)。"""
    if not value:
        return None
    try:
        return datetime.strptime(str(value).strip(), _TIME_FORMAT)
    except (ValueError, TypeError):
        return None


def _fmt(t: Optional[datetime]) -> str:
    return t.strftime(_TIME_FORMAT) if t is not None else ""


def build_timetable(
    artists: Sequence[str],
    open_time=None,
    start_time=None,
    *,
    set_minutes: int = DEFAULT_SET_MINUTES,
    changeover_every_n: int = DEFAULT_CHANGEOVER_EVERY_N,
    changeover_minutes: int = DEFAULT_CHANGEOVER_MINUTES,
    goods_offset_minutes: int = DEFAULT_GOODS_OFFSET_MINUTES,
    goods_duration_minutes: int = DEFAULT_GOODS_DURATION_MINUTES,
    goods_spaces: Sequence[str] = DEFAULT_GOODS_SPACES,
) -> List[TimetableRowDraft]:
    """たたき台のタイムテーブル行を組み立てる。

    引数:
      artists  … ★グリッド番号順(①=先頭 … 最大番号=末尾)の名前リスト。
      open_time … 受け取るが行の計算には使わない。OPEN/START 行はアプリの慣例どおり
                  calculate_timetable_flow が open_time / start_time から合成するので、
                  ここでは行を作らない(重複させない)。引数に残すのは呼び出し側の
                  取り違えを防ぐためと、将来 OPEN 起点の計算を足せるようにするため。
      start_time … 出番の開始時刻 "HH:MM"。ここから積み上げる。

    返り値:
      出演順(= グリッド番号の逆順)に並んだ TimetableRowDraft のリスト。

    計算ルール(§52):
      1. 出順 = グリッド番号の逆(右下=最大番号が最初、①=最後)。
      2. 各出演者は set_minutes 分。時計を進める。
      3. changeover_every_n 組ごとに changeover_minutes 分の転換を挿む。
         転換は行ではなく、直前の出演者の adjustment に載せる(上記「時刻の持ち方」)。
         ★最後の出演者には付けない(終演後にすき間を作っても意味が無いため)。
      4. 物販 = その出演者の終了 + goods_offset_minutes から goods_duration_minutes 分。
         場所は goods_spaces を上から循環(★出演者行のみで数える。転換は行ではないので
         そもそも数に入らない)。

    start_time が読めないとき(未定・None・不正な文字列):
      時刻計算だけを諦め、行そのものは作る。goods_start_time を空文字にして返すので、
      アプリ側では物販時刻が空欄のたたき台になり、あとから開始時刻を入れて
      「保存」すれば calculate_timetable_flow が出番の時刻を埋める。
      ★ここで例外を投げたり空リストを返したりはしない(たたき台が丸ごと消えるため)。
    """
    if not artists:
        return []

    # 1. 出順はグリッド番号の逆
    ordered = list(reversed(list(artists)))
    total = len(ordered)

    clock = _parse_time(start_time)
    spaces = list(goods_spaces or [])
    every_n = int(changeover_every_n or 0)

    rows: List[TimetableRowDraft] = []
    for idx, name in enumerate(ordered):        # idx: 0 始まりの出演順
        # 3. 転換: every_n 組ごと。ただし最後の出演者の後ろには付けない。
        is_changeover_here = (
            every_n > 0
            and (idx + 1) % every_n == 0
            and idx < total - 1
        )
        adjustment = int(changeover_minutes) if is_changeover_here else 0

        # 4. 物販: 出番の終了 + offset から duration 分。場所は出演者行のみで循環。
        goods_start = ""
        if clock is not None:
            end = clock + timedelta(minutes=int(set_minutes))
            goods_start = _fmt(end + timedelta(minutes=int(goods_offset_minutes)))
        place = spaces[idx % len(spaces)] if spaces else ""

        rows.append(TimetableRowDraft(
            artist_name=name,
            duration=int(set_minutes),
            adjustment=adjustment,
            goods_start_time=goods_start,
            goods_duration=int(goods_duration_minutes),
            place=place,
            # グリッドの並び順(§43 の SSOT)。出演順は逆順なので、ここで元の
            # グリッド番号を戻しておかないと下流でグリッドが逆さまになる。
            grid_no=total - idx,
        ))

        # 2. 時計を進める(出番 + 転換)。
        if clock is not None:
            clock += timedelta(minutes=int(set_minutes) + adjustment)

    return rows
