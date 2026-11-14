import pytest
from diet_mcp import db, review_tools, tools

@pytest.fixture(autouse=True)
def database(tmp_path, monkeypatch):
    monkeypatch.setenv('DIET_MCP_DB_PATH', str(tmp_path / 'review.db'))


def test_private_health_does_not_enter_social_summaries():
    with db.connect() as conn:
        conn.execute('INSERT INTO health_daily VALUES (?, ?, ?, ?)', ('2026-11-13', 12227, None, '2026-11-14T00:00:00Z'))
        conn.execute('INSERT INTO health_weights VALUES (?, ?)', ('2026-11-12T15:00:00+00:00', 95))
    daily = review_tools.get_daily_summary('2026-11-13')
    assert daily['health']['daily'][0]['steps'] == 12227
    assert daily['health']['weight_kg'] == {'recorded_days': 1, 'average': 95}
    week = review_tools.get_week_summary('2026-11-13')
    assert week['health']['steps']['recorded_days'] == 1
    assert week['health']['daily'][0]['steps'] is None
    assert 'health' not in tools.get_daily_summary('2026-11-13')
    assert 'health' not in tools.get_week_summary('2026-11-13')


def test_jst_boundaries_daily_weight_average_and_no_carry_forward():
    with db.connect() as conn:
        for t, value in [('2026-11-08T15:00:00+00:00', 94), ('2026-11-09T12:00:00+00:00', 96), ('2026-11-10T00:00:00+00:00', 97), ('2026-11-15T15:00:00+00:00', 150)]:
            conn.execute('INSERT INTO health_weights VALUES (?, ?)', (t, value))
        conn.execute('INSERT INTO health_daily VALUES (?, ?, ?, ?)', ('2026-11-09', 0, 0, 'now'))
    summary = review_tools.get_week_summary('2026-11-09')['health']
    assert summary['weight_kg'] == {'recorded_days': 2, 'average': 96}
    assert summary['daily'][2]['weight_kg'] is None
    assert summary['steps'] == {'recorded_days': 1, 'average': 0}
    assert summary['latest_weight_measurement']['weight_kg'] == 97


def test_missing_health_is_not_zero():
    summary = review_tools.get_daily_summary('2026-11-13')['health']
    assert summary['steps'] == {'recorded_days': 0, 'average': None}
    assert summary['weight_kg']['average'] is None


def test_invalid_date():
    with pytest.raises(ValueError):
        review_tools.get_daily_summary('bad')
