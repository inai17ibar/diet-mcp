from __future__ import annotations

import uuid
from dataclasses import asdict
from datetime import datetime, timedelta
from typing import Any

from diet_mcp import db
from diet_mcp.models import Meal

CALORIE_GOAL_KEY = "daily_calorie_goal"


def _parse_date_str(s: str):
    return datetime.strptime(s, "%Y-%m-%d").date()


def _nutrient_totals(meals: list[Meal]) -> dict[str, float | None]:
    totals: dict[str, float | None] = {}
    for field in ("protein_g", "fat_g", "carbs_g"):
        values = [getattr(m, field) for m in meals if getattr(m, field) is not None]
        totals[field] = sum(values) if values else None
    return totals


def _get_calorie_goal(conn) -> float | None:
    value = db.get_setting(conn, CALORIE_GOAL_KEY)
    return float(value) if value is not None else None


def set_calorie_goal(calories: float) -> dict[str, Any]:
    """1日の目標摂取カロリーを設定する。

    Args:
        calories: 1日の目標カロリー (kcal)

    Returns:
        設定された目標カロリー
    """
    with db.connect() as conn:
        db.set_setting(conn, CALORIE_GOAL_KEY, str(float(calories)))
    return {"daily_calorie_goal": float(calories)}


def add_meal(
    date_str: str,
    time_str: str,
    description: str,
    calories: float,
    tags: list[str] | None = None,
    protein_g: float | None = None,
    fat_g: float | None = None,
    carbs_g: float | None = None,
) -> dict[str, Any]:
    """食事ログを1件追加する。

    重要: この関数は食事1件につき1回呼び出すこと。朝食・昼食・夕食など、
    1日の複数の食事をまとめて1回で記録しないこと(後で個別に編集・削除
    できなくなるため)。複数の食事を記録する場合は、この関数を食事の数
    だけ繰り返し呼び出す。

    Args:
        date_str: 日付 (YYYY-MM-DD)
        time_str: 時刻 (HH:MM)
        description: その1食の内容の説明(例: "バナナとヨーグルト")
        calories: 概算カロリー (kcal)
        tags: 任意のタグ(例: ["朝食", "外食"])
        protein_g: 概算タンパク質量 (g)。不明なら省略可
        fat_g: 概算脂質量 (g)。不明なら省略可
        carbs_g: 概算炭水化物量 (g)。不明なら省略可

    Returns:
        追加されたレコード
    """
    _parse_date_str(date_str)  # validate

    meal = Meal(
        id=str(uuid.uuid4()),
        date=date_str,
        time=time_str,
        description=description,
        calories=float(calories),
        tags=tags or [],
        protein_g=protein_g,
        fat_g=fat_g,
        carbs_g=carbs_g,
    )
    with db.connect() as conn:
        db.insert_meal(conn, meal)

    return asdict(meal)


def update_meal(
    meal_id: str,
    date_str: str | None = None,
    time_str: str | None = None,
    description: str | None = None,
    calories: float | None = None,
    tags: list[str] | None = None,
    protein_g: float | None = None,
    fat_g: float | None = None,
    carbs_g: float | None = None,
) -> dict[str, Any]:
    """既存の食事ログを部分的に更新する。指定したフィールドだけが変更される。

    Args:
        meal_id: 更新するレコードのID(get_daily_summary等の結果に含まれる"id")
        date_str: 変更後の日付 (YYYY-MM-DD)。変更しない場合は省略
        time_str: 変更後の時刻 (HH:MM)。変更しない場合は省略
        description: 変更後の内容。変更しない場合は省略
        calories: 変更後のカロリー (kcal)。変更しない場合は省略
        tags: 変更後のタグ一覧。変更しない場合は省略
        protein_g: 変更後のタンパク質量 (g)。変更しない場合は省略
        fat_g: 変更後の脂質量 (g)。変更しない場合は省略
        carbs_g: 変更後の炭水化物量 (g)。変更しない場合は省略

    Returns:
        更新後のレコード。IDが見つからない場合は {"error": "not_found"}
    """
    if date_str is not None:
        _parse_date_str(date_str)

    with db.connect() as conn:
        meal = db.get_meal(conn, meal_id)
        if meal is None:
            return {"error": "not_found", "id": meal_id}

        if date_str is not None:
            meal.date = date_str
        if time_str is not None:
            meal.time = time_str
        if description is not None:
            meal.description = description
        if calories is not None:
            meal.calories = float(calories)
        if tags is not None:
            meal.tags = tags
        if protein_g is not None:
            meal.protein_g = protein_g
        if fat_g is not None:
            meal.fat_g = fat_g
        if carbs_g is not None:
            meal.carbs_g = carbs_g

        db.update_meal(conn, meal)

    return asdict(meal)


def delete_meal(meal_id: str) -> dict[str, Any]:
    """食事ログを1件削除する。

    Args:
        meal_id: 削除するレコードのID(get_daily_summary等の結果に含まれる"id")

    Returns:
        {"deleted": true/false, "id": meal_id}
    """
    with db.connect() as conn:
        deleted = db.delete_meal(conn, meal_id)
    return {"deleted": deleted, "id": meal_id}


def get_daily_summary(date_str: str) -> dict[str, Any]:
    """指定日の食事ログ・合計カロリー・栄養素内訳・目標カロリーとの比較を返す。

    Args:
        date_str: 日付 (YYYY-MM-DD)
    """
    target_date = _parse_date_str(date_str)
    with db.connect() as conn:
        meals = db.meals_on_date(conn, target_date.isoformat())
        goal = _get_calorie_goal(conn)

    total_calories = sum(m.calories for m in meals)
    result = {
        "date": target_date.isoformat(),
        "total_calories": total_calories,
        "nutrients": _nutrient_totals(meals),
        "meals": [asdict(m) for m in meals],
    }
    if goal is not None:
        result["calorie_goal"] = goal
        result["calories_remaining"] = goal - total_calories
    return result


def get_week_summary(any_date_str: str) -> dict[str, Any]:
    """指定した日付を含む週(月曜始まり7日間)のカロリー合計・栄養素内訳・
    日別内訳・目標カロリーとの比較を返す。

    Args:
        any_date_str: 週の中のどれか1日 (YYYY-MM-DD)
    """
    base_date = _parse_date_str(any_date_str)
    week_start = base_date - timedelta(days=base_date.weekday())
    week_end = week_start + timedelta(days=6)

    with db.connect() as conn:
        meals = db.meals_between(conn, week_start.isoformat(), week_end.isoformat())
        goal = _get_calorie_goal(conn)

    by_date: dict[str, list[Meal]] = {}
    for m in meals:
        by_date.setdefault(m.date, []).append(m)

    daily_list = []
    week_total = 0.0
    current = week_start
    while current <= week_end:
        d_str = current.isoformat()
        day_meals = by_date.get(d_str, [])
        total = sum(m.calories for m in day_meals)
        week_total += total
        day_entry = {
            "date": d_str,
            "total_calories": total,
            "nutrients": _nutrient_totals(day_meals),
            "meals": [asdict(m) for m in day_meals],
        }
        if goal is not None:
            day_entry["calorie_goal"] = goal
            day_entry["calories_remaining"] = goal - total
        daily_list.append(day_entry)
        current += timedelta(days=1)

    result = {
        "start_date": week_start.isoformat(),
        "end_date": week_end.isoformat(),
        "daily": daily_list,
        "week_total_calories": week_total,
        "week_nutrients": _nutrient_totals(meals),
    }
    if goal is not None:
        result["week_calorie_goal"] = goal * 7
        result["week_calories_remaining"] = goal * 7 - week_total
    return result
