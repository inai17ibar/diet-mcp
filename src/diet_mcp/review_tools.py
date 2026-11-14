"""Private MCP summaries. REST summaries used by SNS never call these wrappers."""
from datetime import date, datetime, timedelta, timezone

from diet_mcp import db, tools

JST = timezone(timedelta(hours=9))


def _health_between(start: date, end: date) -> dict:
    lo = datetime.combine(start, datetime.min.time(), JST).astimezone(timezone.utc).isoformat()
    hi = datetime.combine(end + timedelta(days=1), datetime.min.time(), JST).astimezone(timezone.utc).isoformat()
    with db.connect() as conn:
        rows = {r['date']: dict(r) for r in conn.execute(
            'SELECT * FROM health_daily WHERE date BETWEEN ? AND ?', (start.isoformat(), end.isoformat()))}
        weights = [dict(r) for r in conn.execute(
            'SELECT * FROM health_weights WHERE measured_at >= ? AND measured_at < ? ORDER BY measured_at', (lo, hi))]
    by_day = {}
    for weight in weights:
        key = datetime.fromisoformat(weight['measured_at']).astimezone(JST).date().isoformat()
        by_day.setdefault(key, []).append(weight['weight_kg'])
    daily = []
    for i in range((end - start).days + 1):
        key = (start + timedelta(days=i)).isoformat()
        row = rows.get(key, {})
        values = by_day.get(key, [])
        daily.append({'date': key, 'steps': row.get('steps'),
                      'active_energy_kcal': row.get('active_energy_kcal'),
                      'weight_kg': sum(values) / len(values) if values else None,
                      'weight_measurements': len(values), 'activity_imported_at': row.get('updated_at')})
    def summary(field):
        values = [r[field] for r in daily if r[field] is not None]
        return {'recorded_days': len(values), 'average': sum(values) / len(values) if values else None}
    return {'timezone': 'Asia/Tokyo', 'daily': daily,
            'steps': summary('steps'), 'active_energy_kcal': summary('active_energy_kcal'),
            'weight_kg': summary('weight_kg'),
            'latest_weight_measurement': weights[-1] if weights else None,
            'notes': ['Missing values are unknown, not zero. No weight is carried forward.',
                      'Import time is not measurement time; a current day may be incomplete.',
                      'Steps and active energy are activity indicators, not total energy expenditure.',
                      'Food records may be incomplete; correlation does not establish causation.']}


def get_daily_summary(date_str: str) -> dict:
    """指定日の食事・歩数・実測体重・活動量を取得する本人用サマリ。

    date_str: YYYY-MM-DD。健康データ欠測はnull。SNSへ送信しない。
    """
    result = tools.get_daily_summary(date_str)
    target = date.fromisoformat(result['date'])
    result['health'] = _health_between(target, target)
    return result


def get_week_summary(any_date_str: str) -> dict:
    """指定日を含む月〜日の食事・歩数・実測体重を取得する本人用サマリ。

    any_date_str: YYYY-MM-DD。月次/3か月レビューは複数週を取得して対象期間を抽出。
    欠測を0にせず、食事記録日数と体重測定日数を確認して判断する。
    """
    result = tools.get_week_summary(any_date_str)
    result['health'] = _health_between(date.fromisoformat(result['start_date']), date.fromisoformat(result['end_date']))
    return result
