"""ChatGPT Connectorsの一部のリクエストはPKCE(`code_challenge`/`code_verifier`)を
送ってこないことがある(実測: `/authorize`の初回呼び出しにcode_challengeが無く、
MCP SDKの`AuthorizationRequest`は必須フィールドとして扱うため`invalid_request`で
即エラーになっていた)。

MCP SDK側の必須バリデーションは変更できないので、PKCEパラメータが無いリクエストに
対してだけ、固定のダミーverifier/challengeペアを注入する。実際にPKCEを送ってくる
クライアントの検証には一切影響しない。
"""

from __future__ import annotations

import base64
import hashlib
from urllib.parse import parse_qsl, urlencode

_DUMMY_VERIFIER = "diet-mcp-fallback-verifier-for-clients-without-pkce"
_DUMMY_CHALLENGE = base64.urlsafe_b64encode(hashlib.sha256(_DUMMY_VERIFIER.encode()).digest()).decode().rstrip("=")


class OptionalPkceMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = scope["path"]

        if path == "/authorize" and scope["method"] == "GET":
            query = dict(parse_qsl(scope["query_string"].decode()))
            if "code_challenge" not in query:
                query["code_challenge"] = _DUMMY_CHALLENGE
                query.setdefault("code_challenge_method", "S256")
                scope = dict(scope)
                scope["query_string"] = urlencode(query).encode()
            await self.app(scope, receive, send)
            return

        if path == "/token" and scope["method"] == "POST":
            body = b""
            more_body = True
            while more_body:
                message = await receive()
                body += message.get("body", b"")
                more_body = message.get("more_body", False)

            form = dict(parse_qsl(body.decode()))
            if form.get("grant_type") == "authorization_code" and "code_verifier" not in form:
                form["code_verifier"] = _DUMMY_VERIFIER
                body = urlencode(form).encode()

            sent = False

            async def receive_wrapper():
                nonlocal sent
                if not sent:
                    sent = True
                    return {"type": "http.request", "body": body, "more_body": False}
                return {"type": "http.disconnect"}

            await self.app(scope, receive_wrapper, send)
            return

        await self.app(scope, receive, send)
