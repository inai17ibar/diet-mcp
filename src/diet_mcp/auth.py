from __future__ import annotations

import hmac
import json
import os
import secrets
import time

from mcp.server.auth.provider import construct_redirect_uri
from starlette.requests import Request
from starlette.responses import HTMLResponse, RedirectResponse

from diet_mcp import db
from diet_mcp.oauth_provider import AUTH_CODE_TTL_SECONDS

LOGIN_PAGE = """<!doctype html>
<html lang="ja"><head><meta charset="utf-8"><title>diet-mcp ログイン</title></head>
<body style="font-family: sans-serif; max-width: 360px; margin: 80px auto;">
<h1>diet-mcp</h1>
<p>{message}</p>
<form method="post">
<input type="hidden" name="request_id" value="{request_id}">
<input type="password" name="password" placeholder="パスワード" autofocus
       style="width:100%;padding:8px;font-size:16px;box-sizing:border-box;">
<button type="submit" style="width:100%;padding:8px;margin-top:8px;font-size:16px;">許可する</button>
</form>
</body></html>"""


def require_api_key() -> str:
    api_key = os.environ.get("DIET_MCP_API_KEY")
    if not api_key:
        raise RuntimeError(
            "DIET_MCP_API_KEY is not set. Generate one (e.g. `openssl rand -hex 32`) "
            "and set it before starting the server. It doubles as the /login password."
        )
    return api_key


async def handle_login(request: Request):
    api_key = require_api_key()

    if request.method == "GET":
        request_id = request.query_params.get("request_id", "")
        return HTMLResponse(
            LOGIN_PAGE.format(message="ChatGPTからのアクセスを許可しますか？", request_id=request_id)
        )

    form = await request.form()
    request_id = str(form.get("request_id", ""))
    password = str(form.get("password", ""))

    with db.connect() as conn:
        pending = db.get_pending_auth(conn, request_id)
        if pending is None or pending["expires_at"] < time.time():
            return HTMLResponse(
                "リクエストが無効か期限切れです。ChatGPT側からやり直してください。", status_code=400
            )

        if not hmac.compare_digest(password, api_key):
            return HTMLResponse(
                LOGIN_PAGE.format(message="パスワードが違います。", request_id=request_id),
                status_code=401,
            )

        code = secrets.token_urlsafe(32)
        db.save_auth_code(
            conn,
            code=code,
            client_id=pending["client_id"],
            scopes=json.loads(pending["scopes"]),
            code_challenge=pending["code_challenge"],
            redirect_uri=pending["redirect_uri"],
            redirect_uri_provided_explicitly=bool(pending["redirect_uri_provided_explicitly"]),
            resource=pending["resource"],
            expires_at=time.time() + AUTH_CODE_TTL_SECONDS,
        )
        db.delete_pending_auth(conn, request_id)
        redirect_uri = pending["redirect_uri"]
        state = pending["state"]

    return RedirectResponse(construct_redirect_uri(redirect_uri, code=code, state=state), status_code=302)
