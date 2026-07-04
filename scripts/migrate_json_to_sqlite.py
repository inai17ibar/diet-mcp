"""旧バージョン (~/diet-mcp-meals.json) のデータを新しいSQLiteストアに一度だけ移行する。

Usage:
    python scripts/migrate_json_to_sqlite.py [path/to/meals.json]
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from diet_mcp import db  # noqa: E402
from diet_mcp.models import Meal  # noqa: E402


def main() -> None:
    src = Path(sys.argv[1]) if len(sys.argv) > 1 else Path.home() / "diet-mcp-meals.json"
    if not src.exists():
        print(f"移行元ファイルが見つかりません: {src}")
        return

    raw = json.loads(src.read_text(encoding="utf-8"))
    with db.connect() as conn:
        for item in raw:
            meal = Meal(
                id=item["id"],
                date=item["date"],
                time=item.get("time", "00:00"),
                description=item["description"],
                calories=float(item["calories"]),
                tags=item.get("tags", []),
            )
            db.insert_meal(conn, meal)

    print(f"{len(raw)}件を移行しました: {src} -> {db.default_db_path()}")


if __name__ == "__main__":
    main()
