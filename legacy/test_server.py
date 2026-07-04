#!/usr/bin/env python
"""
MCP サーバーの簡易テストスクリプト
"""
import json
from datetime import date

# サーバーモジュールをインポート
from server import add_meal, get_daily_summary, get_week_summary

def test_add_meal():
    """食事追加のテスト"""
    print("=" * 50)
    print("テスト1: 食事を追加")
    print("=" * 50)

    today = date.today().isoformat()
    result = add_meal(
        date_str=today,
        time_str="12:30",
        description="ラーメンと餃子",
        calories=850,
        tags=["昼食", "外食"]
    )

    print(json.dumps(result, ensure_ascii=False, indent=2))
    print()

def test_daily_summary():
    """日次サマリーのテスト"""
    print("=" * 50)
    print("テスト2: 今日の食事ログを取得")
    print("=" * 50)

    today = date.today().isoformat()
    result = get_daily_summary(today)

    print(f"日付: {result['date']}")
    print(f"合計カロリー: {result['total_calories']} kcal")
    print(f"食事数: {len(result['meals'])} 件")
    print()

    for i, meal in enumerate(result['meals'], 1):
        print(f"  {i}. {meal['time']} - {meal['description']} ({meal['calories']} kcal)")
        if meal['tags']:
            print(f"     タグ: {', '.join(meal['tags'])}")
    print()

def test_week_summary():
    """週次サマリーのテスト"""
    print("=" * 50)
    print("テスト3: 今週の食事ログを取得")
    print("=" * 50)

    today = date.today().isoformat()
    result = get_week_summary(today)

    print(f"期間: {result['start_date']} 〜 {result['end_date']}")
    print(f"週合計カロリー: {result['week_total_calories']} kcal")
    print()

    for day in result['daily']:
        if day['meals']:
            print(f"  {day['date']}: {day['total_calories']} kcal ({len(day['meals'])}件)")
    print()

if __name__ == "__main__":
    print("\n🍽️  Diet MCP Server テスト\n")

    try:
        test_add_meal()
        test_daily_summary()
        test_week_summary()

        print("✅ すべてのテストが完了しました！")

    except Exception as e:
        print(f"❌ エラーが発生しました: {e}")
        import traceback
        traceback.print_exc()
