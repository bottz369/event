"""下書き保持 + たたき台プロジェクト作成(段階C C-2a)のテスト。

★実 Storage / 実 DB には一切触らない。
  - Storage は intake_draft_store._bucket を差し替え
  - DB は SessionLocal と repo 関数を差し替え(生 SQL も本物の commit も走らない)

.venv 実行想定:
    .venv/bin/python3 -m pytest tests/test_intake_creation.py -v
"""
from __future__ import annotations

import json
import time

import pytest

from services import intake_creation as ic
from services import intake_draft_store as store

PARSED_DATA = {
    "event_type": "girls",
    "event_date": "2026-11-03",
    "event_name": "rock field ULTRA LIVE",
    "subtitle": "AUTUMN",
    "venue": "上野恩賜公園野外ステージ",
    "venue_url": "https://maps.example/xyz",
    "open_time": "11:30",
    "start_time": "12:00",
    "open_start_note": "※変更の場合あり",
    "ticket_common_note": "※各ドリンク代別",
    "tickets": [
        {"name": "Sチケット", "price": "¥6,000", "note": "前方エリア"},
        {"name": "当日", "price": "各+¥1,000", "note": None},
    ],
    "artists": ["アルテミスの翼", "Luna moon", "リルリボン"],
    "tt_settings": {},
    "free_texts": [
        {"title": "■チケット・入場に関して", "body": "入場は…"},
        {"title": "■注意事項", "body": "ジャンプの禁止…"},
        {"title": "■物販・特典会", "body": "出演者毎の決まりに…"},
    ],
}


# ---------------------------------------------------------------------------
# 下書きストア(Storage はメモリの偽物)
# ---------------------------------------------------------------------------
class _FakeBucket:
    def __init__(self):
        self.files = {}
        self.fail_upload = False
        self.fail_download = False
        self.removed = []

    def upload(self, path=None, file=None, file_options=None):
        if self.fail_upload:
            raise RuntimeError("storage down")
        self.files[path] = file

    def download(self, path):
        if self.fail_download or path not in self.files:
            raise RuntimeError("not found")
        return self.files[path]

    def remove(self, paths):
        for p in paths:
            self.removed.append(p)
            self.files.pop(p, None)


@pytest.fixture
def bucket(monkeypatch):
    b = _FakeBucket()
    monkeypatch.setattr(store, "_bucket", lambda: b)
    return b


def test_draft_roundtrip(bucket):
    did = store.save_draft(PARSED_DATA)
    assert did and len(did) == 32
    assert store.load_draft(did) == PARSED_DATA

    assert store.delete_draft(did) is True
    assert store.load_draft(did) is None
    assert bucket.removed == ["%s/%s.json" % (store.STORAGE_PREFIX, did)]


def test_each_draft_is_its_own_file(bucket):
    """1 件 1 ファイル。同時に 2 件保存しても互いを消さない。"""
    a = store.save_draft({"x": 1})
    b = store.save_draft({"x": 2})
    assert a != b
    assert store.load_draft(a) == {"x": 1}
    assert store.load_draft(b) == {"x": 2}
    assert len(bucket.files) == 2


def _advance_clock(monkeypatch, seconds):
    """store が見る時計だけを進める(time.time 自体を再帰させない)。"""
    real_time = time.time
    monkeypatch.setattr(store.time, "time", lambda: real_time() + seconds)


def test_draft_expires_after_ttl(bucket, monkeypatch):
    did = store.save_draft(PARSED_DATA)
    _advance_clock(monkeypatch, store.DRAFT_TTL_SECONDS + 60)
    assert store.load_draft(did) is None
    # 期限切れは掃除も試みる
    assert bucket.removed, "期限切れの下書きを消していない"


def test_draft_within_ttl_is_kept(bucket, monkeypatch):
    did = store.save_draft(PARSED_DATA)
    _advance_clock(monkeypatch, store.DRAFT_TTL_SECONDS - 60)
    assert store.load_draft(did) == PARSED_DATA


def test_storage_failures_are_safe(bucket):
    """Storage 障害は例外にせず「下書きが無い」に倒す(webhook を落とさない)。"""
    bucket.fail_upload = True
    assert store.save_draft(PARSED_DATA) is None

    bucket.fail_upload = False
    did = store.save_draft(PARSED_DATA)
    bucket.fail_download = True
    assert store.load_draft(did) is None


def test_corrupt_draft_is_treated_as_missing(bucket):
    did = store.save_draft(PARSED_DATA)
    bucket.files["%s/%s.json" % (store.STORAGE_PREFIX, did)] = b"{ not json"
    assert store.load_draft(did) is None


@pytest.mark.parametrize(
    "bad", ["", None, "../../etc/passwd", "abc", "g" * 32, "A" * 32, 123])
def test_malformed_draft_id_is_rejected(bucket, bad):
    """postback から来た id を Storage パスに使う前に弾く(パス細工の防止)。"""
    assert store.load_draft(bad) is None
    assert store.delete_draft(bad) is False
    assert bucket.removed == []


def test_draft_store_is_streamlit_free():
    src = _code_lines("services/intake_draft_store.py")
    assert "import streamlit" not in src
    # DB にも触らない(Storage の JSON だけ)
    for forbidden in ("SessionLocal", "project_repo", "timetable_repo"):
        assert forbidden not in src, f"{forbidden} を使っている"


# ---------------------------------------------------------------------------
# 解析結果 → ProjectDraft の写像
# ---------------------------------------------------------------------------
def test_draft_mapping_basic_fields():
    d = ic.build_draft_from_intake(PARSED_DATA)
    assert d.title == "rock field ULTRA LIVE"
    assert d.subtitle == "AUTUMN"
    assert str(d.event_date) == "2026-11-03"
    assert d.venue_name == "上野恩賜公園野外ステージ"
    assert d.venue_url == "https://maps.example/xyz"
    assert d.open_time == "11:30"
    assert d.start_time == "12:00"


def test_draft_mapping_tickets_go_to_tickets_json_not_flyer_json():
    """チケットの実データは tickets_json(flyer_json のチケット系は書式キー)。"""
    d = ic.build_draft_from_intake(PARSED_DATA)
    assert [t.name for t in d.tickets] == ["Sチケット", "当日"]
    # ★金額は告知文の表記のまま。Web の tickets_json も "¥6,000" 形式
    #   (手作業で作った id=34/38/39 の実データと同じ形)。
    assert [t.price for t in d.tickets] == ["¥6,000", "各+¥1,000"]
    assert [t.note for t in d.tickets] == ["前方エリア", ""]
    # flyer_settings に混ぜ込んでいないこと
    assert "ticket_name" not in d.flyer_settings
    assert set(d.flyer_settings) == {"event_type"}


def test_draft_mapping_common_note_and_free_texts():
    d = ic.build_draft_from_intake(PARSED_DATA)
    assert d.ticket_notes == ["※各ドリンク代別"]
    assert len(d.free_texts) == 3, "自由記述は件数可変(メンズは 3 件)"
    assert d.free_texts[2].title == "■物販・特典会"
    assert d.free_texts[0].content == "入場は…"


def test_draft_mapping_grid_order_is_grid_number_order():
    d = ic.build_draft_from_intake(PARSED_DATA)
    assert d.grid_settings["order"] == ["アルテミスの翼", "Luna moon", "リルリボン"]


@pytest.mark.parametrize("event_type", ["girls", "mens"])
def test_event_type_goes_into_flyer_json(event_type):
    d = ic.build_draft_from_intake(dict(PARSED_DATA, event_type=None),
                                   event_type=event_type)
    assert d.flyer_settings == {ic.EVENT_TYPE_FLYER_KEY: event_type}


def test_explicit_event_type_wins_over_parsed():
    d = ic.build_draft_from_intake(PARSED_DATA, event_type="mens")
    assert d.flyer_settings[ic.EVENT_TYPE_FLYER_KEY] == "mens"


def test_missing_fields_fall_back_to_app_defaults():
    d = ic.build_draft_from_intake({})
    assert d.title == ic.DEFAULT_TITLE
    assert d.event_date is None
    assert d.open_time == ic.DEFAULT_OPEN_TIME
    assert d.start_time == ic.DEFAULT_START_TIME
    assert d.tickets == [] and d.free_texts == []
    assert d.grid_settings["order"] == []
    assert d.flyer_settings == {}


def test_rows_match_build_timetable():
    """TT 行は C-3 の純関数そのもの(既定値)であること。"""
    from services.timetable_engine import build_timetable

    rows = ic.build_rows_from_intake(PARSED_DATA)
    expected = build_timetable(PARSED_DATA["artists"],
                               open_time="11:30", start_time="12:00")
    assert rows == expected
    # 出順はグリッド番号の逆・grid_no は元の番号
    assert [r.artist_name for r in rows] == ["リルリボン", "Luna moon", "アルテミスの翼"]
    assert [r.grid_no for r in rows] == [3, 2, 1]


# ---------------------------------------------------------------------------
# 作成 / 上書き(DB はモック。生 SQL も本物の commit も走らない)
# ---------------------------------------------------------------------------
class _FakeProj:
    def __init__(self, pid):
        self.id = pid


class _FakeSession:
    def __init__(self):
        self.committed = 0
        self.closed = False

    def commit(self):
        self.committed += 1

    def rollback(self):
        pass

    def close(self):
        self.closed = True


@pytest.fixture
def db_spy(monkeypatch):
    """repo 経路を記録用スタブに差し替える。"""
    calls = {"created": [], "applied": [], "saved_rows": [], "got": []}
    session = _FakeSession()

    monkeypatch.setattr(ic, "SessionLocal", lambda: session)

    def _create_project(db, **kw):
        calls["created"].append(kw)
        return _FakeProj(101)

    def _get_project(db, pid):
        calls["got"].append(pid)
        return _FakeProj(pid) if pid != 999 else None

    def _apply_draft(proj, draft, rows=None):
        calls["applied"].append((proj.id, draft))

    def _save_rows(db, pid, rows):
        calls["saved_rows"].append((pid, rows))
        return True

    monkeypatch.setattr(ic.project_repo, "create_project", _create_project)
    monkeypatch.setattr(ic.project_repo, "get_project", _get_project)
    monkeypatch.setattr(ic.project_repo, "apply_draft", _apply_draft)
    monkeypatch.setattr(ic.timetable_repo, "save_rows", _save_rows)
    calls["session"] = session
    return calls


def test_create_new_project_uses_repo_path(db_spy):
    pid = ic.create_project_from_intake({"data": PARSED_DATA})

    assert pid == 101
    assert len(db_spy["created"]) == 1, "create_project を通っていない"
    assert db_spy["created"][0]["title"] == "rock field ULTRA LIVE"
    # 内容は apply_draft、TT 行は save_rows(いずれも既存経路)
    applied_pid, draft = db_spy["applied"][0]
    assert applied_pid == 101 and draft.id == 101
    saved_pid, rows = db_spy["saved_rows"][0]
    assert saved_pid == 101
    assert [r.artist_name for r in rows] == ["リルリボン", "Luna moon", "アルテミスの翼"]
    assert db_spy["session"].closed is True


def test_overwrite_replaces_existing_project(db_spy):
    """上書きは既存 pid を取り、その pid に対して内容と行を作り直す。"""
    pid = ic.create_project_from_intake({"data": PARSED_DATA},
                                        overwrite_project_id=42)

    assert pid == 42
    assert db_spy["created"] == [], "上書きなのに新規作成している"
    assert db_spy["got"] == [42]
    applied_pid, draft = db_spy["applied"][0]
    assert applied_pid == 42 and draft.id == 42
    assert db_spy["saved_rows"][0][0] == 42
    # 新しい解釈で総入れ替えされている
    assert draft.title == "rock field ULTRA LIVE"
    assert draft.grid_settings["order"] == PARSED_DATA["artists"]
    assert len(draft.free_texts) == 3


def test_overwrite_missing_project_returns_none(db_spy):
    assert ic.create_project_from_intake({"data": PARSED_DATA},
                                         overwrite_project_id=999) is None
    assert db_spy["applied"] == [] and db_spy["saved_rows"] == []


def test_save_rows_failure_returns_none(db_spy, monkeypatch):
    monkeypatch.setattr(ic.timetable_repo, "save_rows", lambda db, pid, rows: False)
    assert ic.create_project_from_intake({"data": PARSED_DATA}) is None


def test_bad_parsed_input_returns_none(db_spy):
    assert ic.create_project_from_intake(None) is None
    assert ic.create_project_from_intake({"data": None}) is None
    assert db_spy["created"] == []


def test_accepts_bare_data_dict(db_spy):
    """{"data": ...} でも生の data でも受ける。"""
    assert ic.create_project_from_intake(PARSED_DATA) == 101


def _code_lines(path):
    """コメント行を除いたソース行(説明文の語に反応しないようにする)。"""
    out = []
    for line in open(path, encoding="utf-8").read().splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        out.append(line)
    return "\n".join(out)


def test_creation_service_writes_only_through_repo():
    """生 SQL を書いていないこと。書き込みは repo 経由だけであることを守る。"""
    src = _code_lines("services/intake_creation.py")
    for forbidden in ("text(", ".execute(", "db.add(", "db.delete(",
                      "db.query(", "import streamlit"):
        assert forbidden not in src, f"{forbidden} を使っている"
    # 書き込みは既存 repo 関数だけ
    assert "project_repo.create_project(" in src
    assert "project_repo.apply_draft(" in src
    assert "timetable_repo.save_rows(" in src


# ---------------------------------------------------------------------------
# 日付重複検索(read only)
# ---------------------------------------------------------------------------
def test_find_projects_by_event_date(monkeypatch):
    class P:
        def __init__(self, i, t, d):
            self.id, self.title, self.event_date = i, t, d

    session = _FakeSession()
    monkeypatch.setattr(ic, "SessionLocal", lambda: session)
    monkeypatch.setattr(ic.project_repo, "list_projects", lambda db: [
        P(1, "去年", "2025-11-03"),
        P(7, "同日その1", "2026-11-03"),
        P(9, "同日その2", "2026-11-03"),
        P(3, "別日", "2026-11-04"),
    ])

    found = ic.find_projects_by_event_date("2026-11-03")
    assert [f["id"] for f in found] == [9, 7], "新しい順(id 降順)でない"
    assert found[0]["title"] == "同日その2"
    assert session.closed is True


def test_find_projects_by_event_date_without_date(monkeypatch):
    monkeypatch.setattr(ic.project_repo, "list_projects",
                        lambda db: pytest.fail("日付が無いのに DB を引いた"))
    assert ic.find_projects_by_event_date(None) == []
    assert ic.find_projects_by_event_date("未定") == []


# ---------------------------------------------------------------------------
# #3c: 予定組数の保持
# ---------------------------------------------------------------------------
def test_planned_count_is_saved_into_flyer_json():
    d = ic.build_draft_from_intake(dict(PARSED_DATA, planned_artist_count=27))
    assert d.flyer_settings[ic.PLANNED_ARTIST_COUNT_FLYER_KEY] == 27
    # 種別と同居できる
    assert d.flyer_settings[ic.EVENT_TYPE_FLYER_KEY] == "girls"


@pytest.mark.parametrize("bad", [None, 0, -1, "27", True])
def test_invalid_planned_count_is_not_saved(bad):
    """保持できない値のときはキーごと入れない(= 実組数へフォールバックさせる)。"""
    d = ic.build_draft_from_intake(dict(PARSED_DATA, planned_artist_count=bad))
    assert ic.PLANNED_ARTIST_COUNT_FLYER_KEY not in d.flyer_settings


def test_flyer_settings_only_carries_our_keys():
    """見た目のキー(フォント・位置など)には触らない。"""
    d = ic.build_draft_from_intake(dict(PARSED_DATA, planned_artist_count=27))
    assert set(d.flyer_settings) == {ic.EVENT_TYPE_FLYER_KEY,
                                     ic.PLANNED_ARTIST_COUNT_FLYER_KEY}
