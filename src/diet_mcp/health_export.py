"""Apple ヘルスケアへのエクスポート用の素のREST API。

iOSショートカットから叩かれる想定。ショートカットはOAuth/PKCEのやりとりを
組むのが煩雑なので、ChatGPT向けの `/mcp` とは別に、`DIET_MCP_API_KEY` を
そのままBearerトークンとして使う単純な認証にしている(読み取りと
同期済みマークのみで、書き込み内容は限定的なため)。
"""

from __future__ import annotations

import hmac
from datetime import datetime, timedelta, timezone

from starlette.requests import Request
from starlette.responses import JSONResponse

from diet_mcp import db, tools
from diet_mcp.auth import require_api_key

JST = timezone(timedelta(hours=9))


def _authorized(request: Request) -> bool:
    api_key = require_api_key()
    header = request.headers.get("authorization", "")
    scheme, _, token = header.partition(" ")
    return scheme.lower() == "bearer" and hmac.compare_digest(token, api_key)


async def list_unsynced_meals(request: Request):
    """未同期の食事を返し、同時にclaim(配信済み)の印を付ける。

    ショートカットの二重起動対策: claimからTTL以内の食事は返さないので、
    連打しても2回目には空リストが返り、ヘルスケアへの二重記録が起きない。
    """
    if not _authorized(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)

    with db.connect() as conn:
        meals = db.claim_unsynced_meals(conn)

    return JSONResponse(
        {
            "meals": [
                {
                    "id": m.id,
                    "date": m.date,
                    "time": m.time,
                    "description": m.description,
                    "calories": m.calories,
                    "protein_g": m.protein_g,
                    "fat_g": m.fat_g,
                    "carbs_g": m.carbs_g,
                }
                for m in meals
            ]
        }
    )


async def daily_summary(request: Request):
    """指定日(デフォルト: JSTの今日)の食事サマリを返す読み取り専用API。

    ストーリー画像生成など外部サービス(diet-publisher)向け。
    unsyncedと違い、呼んでも状態は一切変わらない。
    """
    if not _authorized(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)

    date_str = request.query_params.get("date")
    if not date_str:
        date_str = datetime.now(JST).date().isoformat()
    try:
        summary = tools.get_daily_summary(date_str)
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    return JSONResponse(summary)


async def mark_meals_synced(request: Request):
    if not _authorized(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)

    body = await request.json()
    ids = body.get("ids", [])
    if not isinstance(ids, list) or not all(isinstance(i, str) for i in ids):
        return JSONResponse({"error": "ids must be a list of strings"}, status_code=400)

    with db.connect() as conn:
        updated = db.mark_meals_synced(conn, ids)

    return JSONResponse({"updated": updated})


async def mark_all_meals_synced(request: Request):
    """id一覧を組み立てずに済む簡易版。今ある未同期の食事を全部同期済みにする。

    ショートカット側でJSONの配列を組み立てる必要がなく、リクエストボディも不要。
    """
    if not _authorized(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)

    with db.connect() as conn:
        updated = db.mark_all_synced(conn)

    return JSONResponse({"updated": updated})
