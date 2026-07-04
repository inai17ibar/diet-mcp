import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import pytest

from diet_mcp import db, tools


@pytest.fixture(autouse=True)
def temp_db(tmp_path, monkeypatch):
    monkeypatch.setenv("DIET_MCP_DB_PATH", str(tmp_path / "test.db"))
    yield


def test_add_meal_returns_record():
    result = tools.add_meal("2026-07-06", "08:00", "バナナとヨーグルト", 250, ["朝食"])
    assert result["date"] == "2026-07-06"
    assert result["calories"] == 250.0
    assert result["tags"] == ["朝食"]
    assert result["id"]


def test_daily_summary_sums_calories_for_date_only():
    tools.add_meal("2026-07-06", "08:00", "朝食", 250)
    tools.add_meal("2026-07-06", "12:30", "昼食", 600)
    tools.add_meal("2026-07-07", "08:00", "別日の朝食", 300)

    summary = tools.get_daily_summary("2026-07-06")

    assert summary["date"] == "2026-07-06"
    assert summary["total_calories"] == 850
    assert len(summary["meals"]) == 2


def test_daily_summary_empty_day():
    summary = tools.get_daily_summary("2026-07-06")
    assert summary["total_calories"] == 0
    assert summary["meals"] == []


def test_week_summary_covers_monday_to_sunday_and_totals():
    # 2026-07-06 is a Monday
    tools.add_meal("2026-07-06", "08:00", "月", 100)
    tools.add_meal("2026-07-12", "08:00", "日", 200)
    tools.add_meal("2026-07-13", "08:00", "来週の月", 999)  # outside the week

    summary = tools.get_week_summary("2026-07-08")  # any day mid-week

    assert summary["start_date"] == "2026-07-06"
    assert summary["end_date"] == "2026-07-12"
    assert summary["week_total_calories"] == 300
    assert len(summary["daily"]) == 7


def test_invalid_date_raises():
    with pytest.raises(ValueError):
        tools.add_meal("2026/07/06", "08:00", "invalid", 100)


def test_add_meal_with_nutrients():
    result = tools.add_meal(
        "2026-07-06", "08:00", "鶏胸肉", 250, protein_g=40, fat_g=5, carbs_g=0
    )
    assert result["protein_g"] == 40
    assert result["fat_g"] == 5
    assert result["carbs_g"] == 0


def test_daily_summary_nutrient_totals_ignore_missing():
    tools.add_meal("2026-07-06", "08:00", "鶏胸肉", 250, protein_g=40, fat_g=5, carbs_g=0)
    tools.add_meal("2026-07-06", "12:00", "白米", 300, carbs_g=65)  # no protein/fat recorded

    summary = tools.get_daily_summary("2026-07-06")

    assert summary["nutrients"]["protein_g"] == 40
    assert summary["nutrients"]["carbs_g"] == 65
    assert summary["nutrients"]["fat_g"] == 5


def test_daily_summary_nutrients_none_when_never_recorded():
    tools.add_meal("2026-07-06", "08:00", "何か", 250)
    summary = tools.get_daily_summary("2026-07-06")
    assert summary["nutrients"]["protein_g"] is None


def test_update_meal_changes_only_given_fields():
    added = tools.add_meal("2026-07-06", "08:00", "バナナ", 100, ["朝食"])

    updated = tools.update_meal(added["id"], calories=120, protein_g=1.5)

    assert updated["calories"] == 120
    assert updated["protein_g"] == 1.5
    assert updated["description"] == "バナナ"  # unchanged
    assert updated["tags"] == ["朝食"]  # unchanged


def test_update_meal_not_found():
    result = tools.update_meal("does-not-exist", calories=100)
    assert result == {"error": "not_found", "id": "does-not-exist"}


def test_delete_meal():
    added = tools.add_meal("2026-07-06", "08:00", "バナナ", 100)

    result = tools.delete_meal(added["id"])
    assert result == {"deleted": True, "id": added["id"]}

    summary = tools.get_daily_summary("2026-07-06")
    assert summary["meals"] == []


def test_delete_meal_not_found():
    result = tools.delete_meal("does-not-exist")
    assert result == {"deleted": False, "id": "does-not-exist"}


def test_calorie_goal_comparison_in_daily_summary():
    tools.set_calorie_goal(2000)
    tools.add_meal("2026-07-06", "08:00", "朝食", 1500)

    summary = tools.get_daily_summary("2026-07-06")

    assert summary["calorie_goal"] == 2000
    assert summary["calories_remaining"] == 500


def test_calorie_goal_comparison_in_week_summary():
    tools.set_calorie_goal(2000)
    tools.add_meal("2026-07-06", "08:00", "月", 1800)  # Monday

    summary = tools.get_week_summary("2026-07-06")

    assert summary["week_calorie_goal"] == 14000
    monday = summary["daily"][0]
    assert monday["calorie_goal"] == 2000
    assert monday["calories_remaining"] == 200


def test_no_calorie_goal_omits_comparison_fields():
    tools.add_meal("2026-07-06", "08:00", "朝食", 500)
    summary = tools.get_daily_summary("2026-07-06")
    assert "calorie_goal" not in summary
