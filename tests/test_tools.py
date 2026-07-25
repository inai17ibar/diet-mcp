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
    result = tools.add_meal(
        "2026-07-06", "08:00", "バナナとヨーグルト", 250, None, None, None, tags=["朝食"]
    )
    assert result["date"] == "2026-07-06"
    assert result["calories"] == 250.0
    assert result["tags"] == ["朝食"]
    assert result["id"]


def test_daily_summary_sums_calories_for_date_only():
    tools.add_meal("2026-07-06", "08:00", "朝食", 250, None, None, None)
    tools.add_meal("2026-07-06", "12:30", "昼食", 600, None, None, None)
    tools.add_meal("2026-07-07", "08:00", "別日の朝食", 300, None, None, None)

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
    tools.add_meal("2026-07-06", "08:00", "月", 100, None, None, None)
    tools.add_meal("2026-07-12", "08:00", "日", 200, None, None, None)
    tools.add_meal("2026-07-13", "08:00", "来週の月", 999, None, None, None)  # outside the week

    summary = tools.get_week_summary("2026-07-08")  # any day mid-week

    assert summary["start_date"] == "2026-07-06"
    assert summary["end_date"] == "2026-07-12"
    assert summary["week_total_calories"] == 300
    assert len(summary["daily"]) == 7


def test_invalid_date_raises():
    with pytest.raises(ValueError):
        tools.add_meal("2026/07/06", "08:00", "invalid", 100, None, None, None)


def test_add_meal_with_nutrients():
    result = tools.add_meal("2026-07-06", "08:00", "鶏胸肉", 250, 40, 5, 0)
    assert result["protein_g"] == 40
    assert result["fat_g"] == 5
    assert result["carbs_g"] == 0


def test_add_meal_requires_nutrient_args():
    with pytest.raises(TypeError):
        tools.add_meal("2026-07-06", "08:00", "引数不足", 250)


def test_daily_summary_nutrient_totals_ignore_missing():
    tools.add_meal("2026-07-06", "08:00", "鶏胸肉", 250, 40, 5, 0)
    tools.add_meal("2026-07-06", "12:00", "白米", 300, None, None, 65)  # protein/fat unknown

    summary = tools.get_daily_summary("2026-07-06")

    assert summary["nutrients"]["protein_g"] == 40
    assert summary["nutrients"]["carbs_g"] == 65
    assert summary["nutrients"]["fat_g"] == 5


def test_daily_summary_nutrients_none_when_never_recorded():
    tools.add_meal("2026-07-06", "08:00", "何か", 250, None, None, None)
    summary = tools.get_daily_summary("2026-07-06")
    assert summary["nutrients"]["protein_g"] is None


def test_update_meal_changes_only_given_fields():
    added = tools.add_meal(
        "2026-07-06", "08:00", "バナナ", 100, None, None, None, tags=["朝食"]
    )

    updated = tools.update_meal(added["id"], calories=120, protein_g=1.5)

    assert updated["calories"] == 120
    assert updated["protein_g"] == 1.5
    assert updated["description"] == "バナナ"  # unchanged
    assert updated["tags"] == ["朝食"]  # unchanged


def test_update_meal_not_found():
    result = tools.update_meal("does-not-exist", calories=100)
    assert result == {"error": "not_found", "id": "does-not-exist"}


def test_delete_meal():
    added = tools.add_meal("2026-07-06", "08:00", "バナナ", 100, None, None, None)

    result = tools.delete_meal(added["id"])
    assert result == {"deleted": True, "id": added["id"]}

    summary = tools.get_daily_summary("2026-07-06")
    assert summary["meals"] == []


def test_delete_meal_not_found():
    result = tools.delete_meal("does-not-exist")
    assert result == {"deleted": False, "id": "does-not-exist"}


def test_calorie_goal_comparison_in_daily_summary():
    tools.set_calorie_goal(2000)
    tools.add_meal("2026-07-06", "08:00", "朝食", 1500, None, None, None)

    summary = tools.get_daily_summary("2026-07-06")

    assert summary["calorie_goal"] == 2000
    assert summary["calories_remaining"] == 500


def test_calorie_goal_comparison_in_week_summary():
    tools.set_calorie_goal(2000)
    tools.add_meal("2026-07-06", "08:00", "月", 1800, None, None, None)  # Monday

    summary = tools.get_week_summary("2026-07-06")

    assert summary["week_calorie_goal"] == 14000
    monday = summary["daily"][0]
    assert monday["calorie_goal"] == 2000
    assert monday["calories_remaining"] == 200


def test_no_calorie_goal_omits_comparison_fields():
    tools.add_meal("2026-07-06", "08:00", "朝食", 500, None, None, None)
    summary = tools.get_daily_summary("2026-07-06")
    assert "calorie_goal" not in summary


def test_new_meals_are_unsynced_by_default():
    added = tools.add_meal("2026-07-06", "08:00", "朝食", 500, None, None, None)

    with db.connect() as conn:
        unsynced = db.unsynced_meals(conn)

    assert [m.id for m in unsynced] == [added["id"]]


def test_mark_meals_synced_excludes_them_from_unsynced():
    a = tools.add_meal("2026-07-06", "08:00", "朝食", 500, None, None, None)
    b = tools.add_meal("2026-07-06", "12:00", "昼食", 700, None, None, None)

    with db.connect() as conn:
        updated = db.mark_meals_synced(conn, [a["id"]])
        unsynced = db.unsynced_meals(conn)

    assert updated == 1
    assert [m.id for m in unsynced] == [b["id"]]


def test_updating_a_meal_does_not_reset_synced_flag():
    added = tools.add_meal("2026-07-06", "08:00", "朝食", 500, None, None, None)
    with db.connect() as conn:
        db.mark_meals_synced(conn, [added["id"]])

    tools.update_meal(added["id"], calories=600)

    with db.connect() as conn:
        unsynced = db.unsynced_meals(conn)
    assert unsynced == []


def test_mark_all_synced_clears_claimed_meals():
    tools.add_meal("2026-07-06", "08:00", "朝食", 500, None, None, None)
    tools.add_meal("2026-07-06", "12:00", "昼食", 700, None, None, None)

    with db.connect() as conn:
        db.claim_unsynced_meals(conn)  # ショートカットへの配信に相当
        updated = db.mark_all_synced(conn)
        unsynced = db.unsynced_meals(conn)

    assert updated == 2
    assert unsynced == []


def test_mark_all_synced_only_touches_unsynced_rows():
    a = tools.add_meal("2026-07-06", "08:00", "朝食", 500, None, None, None)
    tools.add_meal("2026-07-06", "12:00", "昼食", 700, None, None, None)

    with db.connect() as conn:
        db.mark_meals_synced(conn, [a["id"]])
        db.claim_unsynced_meals(conn)
        updated = db.mark_all_synced(conn)  # only the second meal is still unsynced

    assert updated == 1


def test_claim_unsynced_second_call_returns_empty():
    """ショートカット二重起動の再現: 2回目のclaimは空リストになる。"""
    added = tools.add_meal("2026-07-06", "08:00", "朝食", 500, None, None, None)

    with db.connect() as conn:
        first = db.claim_unsynced_meals(conn)
        second = db.claim_unsynced_meals(conn)

    assert [m.id for m in first] == [added["id"]]
    assert second == []


def test_claim_unsynced_reappears_after_ttl():
    """claimされたままヘルスケアに書き込まれなかった食事はTTL後に再配信される。"""
    added = tools.add_meal("2026-07-06", "08:00", "朝食", 500, None, None, None)

    with db.connect() as conn:
        db.claim_unsynced_meals(conn)
        reclaimed = db.claim_unsynced_meals(conn, ttl_seconds=-1)

    assert [m.id for m in reclaimed] == [added["id"]]


def test_mark_all_synced_skips_meals_added_mid_sync():
    """同期中に追加された食事は未claimなので同期済み扱いにならない。"""
    a = tools.add_meal("2026-07-06", "08:00", "朝食", 500, None, None, None)

    with db.connect() as conn:
        db.claim_unsynced_meals(conn)

    b = tools.add_meal("2026-07-06", "12:00", "昼食", 700, None, None, None)

    with db.connect() as conn:
        updated = db.mark_all_synced(conn)
        unsynced = db.unsynced_meals(conn)
        next_claim = db.claim_unsynced_meals(conn)

    assert updated == 1  # aだけ同期済みになる
    assert [m.id for m in unsynced] == [b["id"]]
    assert [m.id for m in next_claim] == [b["id"]]
    assert a["id"] not in [m.id for m in next_claim]
