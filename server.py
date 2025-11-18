# server.py
"""
Diet / Meal Log MCP Server

機能:
- meals.json に食事ログを保存
- MCPツール:
    - add_meal
    - get_daily_summary
    - get_week_summary
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, asdict
from datetime import datetime, date, timedelta
from pathlib import Path
from typing import List, Optional, Dict, Any

from mcp.server.fastmcp import FastMCP

# =========================
# 設定
# =========================

MEALS_FILE = Path("meals.json")

mcp = FastMCP("Diet Meal Log Server")


# =========================
# データモデル
# =========================

@dataclass
class Meal:
    id: str
    date: str          # "YYYY-MM-DD"
    time: str          # "HH:MM"
    description: str
    calories: float
    tags: List[str]


def _load_meals() -> List[Meal]:
    if not MEALS_FILE.exists():
        return []
    with MEALS_FILE.open("r", encoding="utf-8") as f:
        raw = json.load(f)
    meals: List[Meal] = []
    for item in raw:
        meals.append(
            Meal(
                id=item.get("id", str(uuid.uuid4())),
                date=item["date"],
                time=item.get("time", "00:00"),
                description=item["description"],
                calories=float(item["calories"]),
                tags=item.get("tags", []),
            )
        )
    return meals


def _save_meals(meals: List[Meal]) -> None:
    data = [asdict(m) for m in meals]
    with MEALS_FILE.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _parse_date_str(s: str) -> date:
    """YYYY-MM-DD 形式を date に変換。例: '2025-11-18'"""
    return datetime.strptime(s, "%Y-%m-%d").date()


# =========================
# MCPツール定義
# =========================

@mcp.tool()
def add_meal(
    date_str: str,
    time_str: str,
    description: str,
    calories: float,
    tags: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """
    食事ログを1件追加するツール。

    Args:
        date_str: 日付 (YYYY-MM-DD)
        time_str: 時刻 (HH:MM) 適当でも可
        description: 食事内容の説明（例: "バナナとヨーグルト"）
        calories: 概算カロリー (kcal)
        tags: 任意のタグ（例: ["朝食", "外食"]）

    Returns:
        追加されたレコード (JSON形式)
    """
    tags = tags or []

    # 日付形式の軽いバリデーション
    _ = _parse_date_str(date_str)

    meals = _load_meals()

    meal = Meal(
        id=str(uuid.uuid4()),
        date=date_str,
        time=time_str,
        description=description,
        calories=float(calories),
        tags=tags,
    )

    meals.append(meal)
    # 日付・時刻でソートしておくと後で見やすい
    meals.sort(key=lambda m: (m.date, m.time))
    _save_meals(meals)

    return asdict(meal)


@mcp.tool()
def get_daily_summary(date_str: str) -> Dict[str, Any]:
    """
    指定日の食事ログの一覧と合計カロリーを返すツール。

    Args:
        date_str: 日付 (YYYY-MM-DD)

    Returns:
        {
          "date": "...",
          "total_calories": float,
          "meals": [Meal...]
        }
    """
    target_date = _parse_date_str(date_str)
    meals = _load_meals()

    day_meals = [m for m in meals if m.date == target_date.isoformat()]
    total = sum(m.calories for m in day_meals)

    return {
        "date": target_date.isoformat(),
        "total_calories": total,
        "meals": [asdict(m) for m in day_meals],
    }


@mcp.tool()
def get_week_summary(any_date_str: str) -> Dict[str, Any]:
    """
    指定した日付を含む週(7日間)のカロリー合計と日別内訳を返すツール。

    Args:
        any_date_str: 週の中のどれか1日 (YYYY-MM-DD)

    Returns:
        {
          "start_date": "週の開始日(月曜)",
          "end_date": "週の終了日(日曜)",
          "daily": [
            {
              "date": "...",
              "total_calories": float,
              "meals": [Meal...]
            },
            ...
          ],
          "week_total_calories": float
        }
    """
    base_date = _parse_date_str(any_date_str)

    # 月曜日を週の開始とする
    weekday = base_date.weekday()  # Monday=0 ... Sunday=6
    week_start = base_date - timedelta(days=weekday)
    week_end = week_start + timedelta(days=6)

    meals = _load_meals()

    daily_list = []
    week_total = 0.0

    current = week_start
    while current <= week_end:
        d_str = current.isoformat()
        day_meals = [m for m in meals if m.date == d_str]
        total = sum(m.calories for m in day_meals)
        week_total += total

        daily_list.append(
            {
                "date": d_str,
                "total_calories": total,
                "meals": [asdict(m) for m in day_meals],
            }
        )

        current += timedelta(days=1)

    return {
        "start_date": week_start.isoformat(),
        "end_date": week_end.isoformat(),
        "daily": daily_list,
        "week_total_calories": week_total,
    }


if __name__ == "__main__":
    # MCPサーバーとして起動
    mcp.run()
