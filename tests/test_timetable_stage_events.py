import copy

import pytest

from services.timetable_stage_events import add_stage_events


def test_entry_before_start_and_changeover_preserve_performance_and_goods():
    table = [['10:30 - 10:50', 'UK', '11:00 - 12:00', ''],
             ['10:55 - 11:15', '君色パティシエ', '11:25 - 12:25', '']]
    before = copy.deepcopy(table)
    events = [dict(before_artist='UK', label='VIP入場', minutes=5),
              dict(before_artist='君色パティシエ', label='VIP入れ替え', minutes=5)]
    result = add_stage_events(table, events)
    assert result == [['10:25 - 10:30', 'VIP入場', '', ''], table[0],
                      ['10:50 - 10:55', 'VIP入れ替え', '', ''], table[1]]
    assert table == before
    assert add_stage_events(table) is table


def test_notices_follow_artist_time_edits_and_reject_overlap():
    events = [dict(before_artist='B', label='VIP入れ替え', minutes=5)]
    assert add_stage_events([['11:00 - 11:20', 'A', '', ''], ['11:30 - 11:50', 'B', '', '']], events)[1][0] == '11:25 - 11:30'
    with pytest.raises(ValueError, match='重なって'):
        add_stage_events([['11:00 - 11:20', 'A', '', ''], ['11:24 - 11:44', 'B', '', '']], events)


def test_missing_hidden_artist_does_not_create_an_orphan_notice():
    table = [['11:00 - 11:20', 'A', '', '']]
    assert add_stage_events(table, [dict(before_artist='hidden', label='VIP入れ替え', minutes=5)]) == table
