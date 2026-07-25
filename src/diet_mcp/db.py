from __future__ import annotations

import json
import os
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path

from diet_mcp.models import Meal

SCHEMA = """
CREATE TABLE IF NOT EXISTS meals (
    id TEXT PRIMARY KEY,
    date TEXT NOT NULL,
    time TEXT NOT NULL,
    description TEXT NOT NULL,
    calories REAL NOT NULL,
    tags TEXT NOT NULL DEFAULT '[]'
);
CREATE INDEX IF NOT EXISTS idx_meals_date ON meals(date);

CREATE TABLE IF NOT EXISTS oauth_clients (
    client_id TEXT PRIMARY KEY,
    data TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS oauth_pending_auth (
    request_id TEXT PRIMARY KEY,
    client_id TEXT NOT NULL,
    state TEXT,
    scopes TEXT NOT NULL,
    code_challenge TEXT NOT NULL,
    redirect_uri TEXT NOT NULL,
    redirect_uri_provided_explicitly INTEGER NOT NULL,
    resource TEXT,
    expires_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS oauth_codes (
    code TEXT PRIMARY KEY,
    client_id TEXT NOT NULL,
    scopes TEXT NOT NULL,
    code_challenge TEXT NOT NULL,
    redirect_uri TEXT NOT NULL,
    redirect_uri_provided_explicitly INTEGER NOT NULL,
    resource TEXT,
    expires_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS oauth_access_tokens (
    access_token TEXT PRIMARY KEY,
    client_id TEXT NOT NULL,
    scopes TEXT NOT NULL,
    resource TEXT,
    expires_at REAL
);

CREATE TABLE IF NOT EXISTS oauth_refresh_tokens (
    refresh_token TEXT PRIMARY KEY,
    client_id TEXT NOT NULL,
    scopes TEXT NOT NULL,
    expires_at REAL
);

CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""

# columns added after the initial release; applied via ALTER TABLE for
# databases created before this field existed (SQLite has no
# "ADD COLUMN IF NOT EXISTS", so we check PRAGMA table_info first)
_MEAL_COLUMN_MIGRATIONS = {
    "protein_g": "REAL",
    "fat_g": "REAL",
    "carbs_g": "REAL",
    "synced_to_health": "INTEGER NOT NULL DEFAULT 0",
    "health_claimed_at": "REAL",
}


def _migrate(conn: sqlite3.Connection) -> None:
    existing = {row["name"] for row in conn.execute("PRAGMA table_info(meals)").fetchall()}
    for column, sql_type in _MEAL_COLUMN_MIGRATIONS.items():
        if column not in existing:
            conn.execute(f"ALTER TABLE meals ADD COLUMN {column} {sql_type}")


def default_db_path() -> Path:
    override = os.environ.get("DIET_MCP_DB_PATH")
    if override:
        return Path(override)
    return Path.home() / ".diet-mcp" / "diet-mcp.db"


@contextmanager
def connect(db_path: Path | None = None):
    path = db_path or default_db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        conn.executescript(SCHEMA)
        _migrate(conn)
        yield conn
        conn.commit()
    finally:
        conn.close()


def _row_to_meal(row: sqlite3.Row) -> Meal:
    return Meal(
        id=row["id"],
        date=row["date"],
        time=row["time"],
        description=row["description"],
        calories=row["calories"],
        tags=json.loads(row["tags"]),
        protein_g=row["protein_g"],
        fat_g=row["fat_g"],
        carbs_g=row["carbs_g"],
    )


def insert_meal(conn: sqlite3.Connection, meal: Meal) -> None:
    conn.execute(
        "INSERT INTO meals (id, date, time, description, calories, tags, protein_g, fat_g, carbs_g) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            meal.id,
            meal.date,
            meal.time,
            meal.description,
            meal.calories,
            json.dumps(meal.tags),
            meal.protein_g,
            meal.fat_g,
            meal.carbs_g,
        ),
    )


def get_meal(conn: sqlite3.Connection, meal_id: str) -> Meal | None:
    row = conn.execute("SELECT * FROM meals WHERE id = ?", (meal_id,)).fetchone()
    return _row_to_meal(row) if row else None


def update_meal(conn: sqlite3.Connection, meal: Meal) -> None:
    conn.execute(
        "UPDATE meals SET date=?, time=?, description=?, calories=?, tags=?, "
        "protein_g=?, fat_g=?, carbs_g=? WHERE id=?",
        (
            meal.date,
            meal.time,
            meal.description,
            meal.calories,
            json.dumps(meal.tags),
            meal.protein_g,
            meal.fat_g,
            meal.carbs_g,
            meal.id,
        ),
    )


def delete_meal(conn: sqlite3.Connection, meal_id: str) -> bool:
    cursor = conn.execute("DELETE FROM meals WHERE id = ?", (meal_id,))
    return cursor.rowcount > 0


def meals_on_date(conn: sqlite3.Connection, date_str: str) -> list[Meal]:
    rows = conn.execute(
        "SELECT * FROM meals WHERE date = ? ORDER BY time", (date_str,)
    ).fetchall()
    return [_row_to_meal(r) for r in rows]


def meals_between(conn: sqlite3.Connection, start_date: str, end_date: str) -> list[Meal]:
    rows = conn.execute(
        "SELECT * FROM meals WHERE date BETWEEN ? AND ? ORDER BY date, time",
        (start_date, end_date),
    ).fetchall()
    return [_row_to_meal(r) for r in rows]


# ---- Health export sync tracking ----

# claim(配信)からこの秒数以内の食事は再配信しない。ショートカットの
# 二重起動対策で、ヘルスケアに書き込まれないままこの時間が過ぎた場合は
# 再び unsynced として配信される。
HEALTH_CLAIM_TTL_SECONDS = 600


def unsynced_meals(conn: sqlite3.Connection) -> list[Meal]:
    rows = conn.execute(
        "SELECT * FROM meals WHERE synced_to_health = 0 ORDER BY date, time"
    ).fetchall()
    return [_row_to_meal(r) for r in rows]


def claim_unsynced_meals(
    conn: sqlite3.Connection, *, ttl_seconds: float = HEALTH_CLAIM_TTL_SECONDS
) -> list[Meal]:
    """未同期の食事を取得し、同時にclaim(配信済み)の印を付ける。

    ショートカットを連打しても、2回目以降のリクエストはTTL内なので
    空リストが返り、ヘルスケアへの二重書き込みが起きない。
    UPDATE ... RETURNING で取得と印付けを1文で行い、並行リクエスト間の
    取りこぼしを防ぐ。
    """
    now = time.time()
    rows = conn.execute(
        "UPDATE meals SET health_claimed_at = ? "
        "WHERE synced_to_health = 0 "
        "AND (health_claimed_at IS NULL OR health_claimed_at < ?) "
        "RETURNING *",
        (now, now - ttl_seconds),
    ).fetchall()
    meals = [_row_to_meal(r) for r in rows]
    meals.sort(key=lambda m: (m.date, m.time))
    return meals


def mark_meals_synced(conn: sqlite3.Connection, meal_ids: list[str]) -> int:
    if not meal_ids:
        return 0
    placeholders = ",".join("?" for _ in meal_ids)
    cursor = conn.execute(
        f"UPDATE meals SET synced_to_health = 1 WHERE id IN ({placeholders})",
        meal_ids,
    )
    return cursor.rowcount


def mark_all_synced(conn: sqlite3.Connection) -> int:
    """claim済み(=ショートカットに配信済み)の食事だけを同期済みにする。

    同期の最中に追加された食事(未claim)を誤って同期済みにしない。
    """
    cursor = conn.execute(
        "UPDATE meals SET synced_to_health = 1 "
        "WHERE synced_to_health = 0 AND health_claimed_at IS NOT NULL"
    )
    return cursor.rowcount


# ---- settings (single-user key/value, e.g. daily calorie goal) ----


def get_setting(conn: sqlite3.Connection, key: str) -> str | None:
    row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else None


def set_setting(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        "INSERT INTO settings (key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )


# ---- OAuth: clients ----


def get_oauth_client(conn: sqlite3.Connection, client_id: str) -> str | None:
    row = conn.execute("SELECT data FROM oauth_clients WHERE client_id = ?", (client_id,)).fetchone()
    return row["data"] if row else None


def save_oauth_client(conn: sqlite3.Connection, client_id: str, data_json: str) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO oauth_clients (client_id, data) VALUES (?, ?)",
        (client_id, data_json),
    )


# ---- OAuth: pending authorization (between /authorize and /login) ----


def save_pending_auth(
    conn: sqlite3.Connection,
    request_id: str,
    client_id: str,
    state: str | None,
    scopes: list[str],
    code_challenge: str,
    redirect_uri: str,
    redirect_uri_provided_explicitly: bool,
    resource: str | None,
    expires_at: float,
) -> None:
    conn.execute(
        "INSERT INTO oauth_pending_auth "
        "(request_id, client_id, state, scopes, code_challenge, redirect_uri, "
        "redirect_uri_provided_explicitly, resource, expires_at) VALUES (?,?,?,?,?,?,?,?,?)",
        (
            request_id,
            client_id,
            state,
            json.dumps(scopes),
            code_challenge,
            redirect_uri,
            int(redirect_uri_provided_explicitly),
            resource,
            expires_at,
        ),
    )


def get_pending_auth(conn: sqlite3.Connection, request_id: str) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM oauth_pending_auth WHERE request_id = ?", (request_id,)
    ).fetchone()


def delete_pending_auth(conn: sqlite3.Connection, request_id: str) -> None:
    conn.execute("DELETE FROM oauth_pending_auth WHERE request_id = ?", (request_id,))


# ---- OAuth: authorization codes ----


def save_auth_code(
    conn: sqlite3.Connection,
    code: str,
    client_id: str,
    scopes: list[str],
    code_challenge: str,
    redirect_uri: str,
    redirect_uri_provided_explicitly: bool,
    resource: str | None,
    expires_at: float,
) -> None:
    conn.execute(
        "INSERT INTO oauth_codes "
        "(code, client_id, scopes, code_challenge, redirect_uri, "
        "redirect_uri_provided_explicitly, resource, expires_at) VALUES (?,?,?,?,?,?,?,?)",
        (
            code,
            client_id,
            json.dumps(scopes),
            code_challenge,
            redirect_uri,
            int(redirect_uri_provided_explicitly),
            resource,
            expires_at,
        ),
    )


def get_auth_code(conn: sqlite3.Connection, code: str) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM oauth_codes WHERE code = ?", (code,)).fetchone()


def delete_auth_code(conn: sqlite3.Connection, code: str) -> None:
    conn.execute("DELETE FROM oauth_codes WHERE code = ?", (code,))


# ---- OAuth: access / refresh tokens ----


def save_access_token(
    conn: sqlite3.Connection,
    access_token: str,
    client_id: str,
    scopes: list[str],
    resource: str | None,
    expires_at: float | None,
) -> None:
    conn.execute(
        "INSERT INTO oauth_access_tokens (access_token, client_id, scopes, resource, expires_at) "
        "VALUES (?,?,?,?,?)",
        (access_token, client_id, json.dumps(scopes), resource, expires_at),
    )


def get_access_token(conn: sqlite3.Connection, access_token: str) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM oauth_access_tokens WHERE access_token = ?", (access_token,)
    ).fetchone()


def delete_access_token(conn: sqlite3.Connection, access_token: str) -> None:
    conn.execute("DELETE FROM oauth_access_tokens WHERE access_token = ?", (access_token,))


def save_refresh_token(
    conn: sqlite3.Connection,
    refresh_token: str,
    client_id: str,
    scopes: list[str],
    expires_at: float | None,
) -> None:
    conn.execute(
        "INSERT INTO oauth_refresh_tokens (refresh_token, client_id, scopes, expires_at) VALUES (?,?,?,?)",
        (refresh_token, client_id, json.dumps(scopes), expires_at),
    )


def get_refresh_token(conn: sqlite3.Connection, refresh_token: str) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM oauth_refresh_tokens WHERE refresh_token = ?", (refresh_token,)
    ).fetchone()


def delete_refresh_token(conn: sqlite3.Connection, refresh_token: str) -> None:
    conn.execute("DELETE FROM oauth_refresh_tokens WHERE refresh_token = ?", (refresh_token,))
