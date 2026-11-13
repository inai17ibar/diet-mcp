"""Private Apple Health ingestion. Never added to public/social summaries."""
from __future__ import annotations

import hmac
import json
import os
from datetime import date, datetime, timedelta, timezone

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator
from starlette.requests import Request
from starlette.responses import JSONResponse

from diet_mcp import db, tools
from diet_mcp.health_export import JST, _authorized


class DailyHealth(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    date: date
    steps: int | None = Field(default=None, ge=0, le=200000, strict=True)
    active_energy_kcal: float | None = Field(default=None, ge=0, le=20000)


class Weight(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    measured_at: datetime
    weight_kg: float = Field(gt=0, le=500)

    @field_validator("measured_at")
    @classmethod
    def aware(cls, value):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("measured_at requires a timezone")
        return value


class HealthBatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    daily: list[DailyHealth] = Field(default_factory=list, max_length=31)
    weights: list[Weight] = Field(default_factory=list, max_length=500)


async def import_health(request: Request):
    # Separate, revocable write-only credential: do not put the login key on iPhone.
    expected = os.environ.get("DIET_HEALTH_IMPORT_TOKEN", "")
    scheme, _, token = request.headers.get("authorization", "").partition(" ")
    if not expected or scheme.lower() != "bearer" or not hmac.compare_digest(token, expected):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > 256000:
            return JSONResponse({"error": "payload too large"}, status_code=413)
    try:
        batch = HealthBatch.model_validate(json.loads(body))
        if len({d.date for d in batch.daily}) != len(batch.daily):
            raise ValueError("duplicate daily dates")
        keys = [w.measured_at.astimezone(timezone.utc).isoformat() for w in batch.weights]
        if len(set(keys)) != len(keys):
            raise ValueError("duplicate measurement timestamps")
    except (ValueError, ValidationError):
        return JSONResponse({"error": "invalid health payload; check dates, units and values"}, status_code=400)
    now = datetime.now(timezone.utc).isoformat()
    with db.connect() as conn:
        for day in batch.daily:
            # Omitted/null metrics preserve existing values. Zero is a real measurement.
            conn.execute(
                "INSERT INTO health_daily VALUES (?, ?, ?, ?) ON CONFLICT(date) DO UPDATE SET "
                "steps=COALESCE(excluded.steps, health_daily.steps), "
                "active_energy_kcal=COALESCE(excluded.active_energy_kcal, health_daily.active_energy_kcal), "
                "updated_at=excluded.updated_at",
                (day.date.isoformat(), day.steps, day.active_energy_kcal, now),
            )
        for key, weight in zip(keys, batch.weights):
            conn.execute(
                "INSERT INTO health_weights VALUES (?, ?) ON CONFLICT(measured_at) "
                "DO UPDATE SET weight_kg=excluded.weight_kg", (key, weight.weight_kg),
            )
    return JSONResponse({"daily_received": len(batch.daily), "weights_received": len(batch.weights)})


def get_health_week(date_str: str) -> dict:
    anchor = date.fromisoformat(date_str)
    start = anchor - timedelta(days=anchor.weekday())
    end = start + timedelta(days=6)
    with db.connect() as conn:
        days = {r["date"]: dict(r) for r in conn.execute(
            "SELECT * FROM health_daily WHERE date BETWEEN ? AND ?", (start.isoformat(), end.isoformat()))}
        lo = datetime.combine(start, datetime.min.time(), JST).astimezone(timezone.utc).isoformat()
        hi = datetime.combine(end + timedelta(days=1), datetime.min.time(), JST).astimezone(timezone.utc).isoformat()
        weights = [dict(r) for r in conn.execute(
            "SELECT * FROM health_weights WHERE measured_at >= ? AND measured_at < ? ORDER BY measured_at", (lo, hi))]
    # Average within each JST day first: repeated weigh-ins must not overweight that day.
    weight_days = {}
    for w in weights:
        key = datetime.fromisoformat(w["measured_at"]).astimezone(JST).date().isoformat()
        weight_days.setdefault(key, []).append(w["weight_kg"])
    daily = []
    for i in range(7):
        key = (start + timedelta(days=i)).isoformat()
        row = days.get(key, {})
        values = weight_days.get(key, [])
        daily.append({"date": key, "steps": row.get("steps"),
                      "active_energy_kcal": row.get("active_energy_kcal"),
                      "weight_kg": sum(values) / len(values) if values else None})
    def metric(name):
        values = [d[name] for d in daily if d[name] is not None]
        return {"recorded_days": len(values), "average": sum(values) / len(values) if values else None}
    meals = tools.get_week_summary(date_str)
    recorded = [d for d in meals["daily"] if d.get("meals")]
    return {"start_date": start.isoformat(), "end_date": end.isoformat(), "timezone": "Asia/Tokyo",
            "daily": daily, "steps": metric("steps"), "active_energy_kcal": metric("active_energy_kcal"),
            "weight_kg": metric("weight_kg"),
            "food": {"recorded_days": len(recorded),
                     "average_calories": sum(d["total_calories"] for d in recorded) / len(recorded) if recorded else None},
            "note": "Food recording may be incomplete. Active energy is not total daily expenditure."}


async def health_week_summary(request: Request):
    if not _authorized(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    try:
        return JSONResponse(get_health_week(request.query_params.get("date") or datetime.now(JST).date().isoformat()))
    except ValueError:
        return JSONResponse({"error": "invalid date"}, status_code=400)
