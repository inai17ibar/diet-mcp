"""単一ユーザー向けの最小限のOAuth 2.1認可サーバー実装。

ChatGPT Connectorsが要求する動的クライアント登録(RFC 7591) + 認可コード
フロー(PKCE)に対応するため、mcpパッケージの`OAuthAuthorizationServerProvider`
プロトコルを実装する。第三者IdPには委譲せず、このサーバー自身が認可サーバー
になる。ログインはアカウント所有者1人だけを想定し、`DIET_MCP_API_KEY`を
そのままログインパスワードとして流用する(共有シークレットとしての用途は
変わらず、使われ方がヘッダー直渡しからログインフォームに変わっただけ)。
"""

from __future__ import annotations

import json
import secrets
import time

from mcp.server.auth.provider import (
    AccessToken,
    AuthorizationCode,
    AuthorizationParams,
    OAuthAuthorizationServerProvider,
    RefreshToken,
)
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken

from diet_mcp import db

AUTH_CODE_TTL_SECONDS = 600
PENDING_AUTH_TTL_SECONDS = 1800
ACCESS_TOKEN_TTL_SECONDS = 3600

SCOPE = "meals"
DEFAULT_SCOPES = [SCOPE]


class DietMcpOAuthProvider(OAuthAuthorizationServerProvider[AuthorizationCode, RefreshToken, AccessToken]):
    def __init__(self, issuer_url: str):
        self._issuer_url = issuer_url.rstrip("/")

    # ---- clients (dynamic client registration) ----

    async def get_client(self, client_id: str) -> OAuthClientInformationFull | None:
        with db.connect() as conn:
            data = db.get_oauth_client(conn, client_id)
        return OAuthClientInformationFull.model_validate_json(data) if data else None

    async def register_client(self, client_info: OAuthClientInformationFull) -> None:
        with db.connect() as conn:
            db.save_oauth_client(conn, client_info.client_id, client_info.model_dump_json())

    # ---- authorization: hand off to our own /login page ----

    async def authorize(self, client: OAuthClientInformationFull, params: AuthorizationParams) -> str:
        request_id = secrets.token_urlsafe(16)
        with db.connect() as conn:
            db.save_pending_auth(
                conn,
                request_id=request_id,
                client_id=client.client_id,
                state=params.state,
                scopes=params.scopes or DEFAULT_SCOPES,
                code_challenge=params.code_challenge,
                redirect_uri=str(params.redirect_uri),
                redirect_uri_provided_explicitly=params.redirect_uri_provided_explicitly,
                resource=params.resource,
                expires_at=time.time() + PENDING_AUTH_TTL_SECONDS,
            )
        return f"{self._issuer_url}/login?request_id={request_id}"

    # ---- authorization codes ----

    async def load_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: str
    ) -> AuthorizationCode | None:
        with db.connect() as conn:
            row = db.get_auth_code(conn, authorization_code)
        if row is None or row["client_id"] != client.client_id:
            return None
        return AuthorizationCode(
            code=row["code"],
            client_id=row["client_id"],
            scopes=json.loads(row["scopes"]),
            expires_at=row["expires_at"],
            code_challenge=row["code_challenge"],
            redirect_uri=row["redirect_uri"],
            redirect_uri_provided_explicitly=bool(row["redirect_uri_provided_explicitly"]),
            resource=row["resource"],
        )

    async def exchange_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: AuthorizationCode
    ) -> OAuthToken:
        with db.connect() as conn:
            db.delete_auth_code(conn, authorization_code.code)

            access_token = secrets.token_urlsafe(32)
            refresh_token = secrets.token_urlsafe(32)
            access_expires_at = time.time() + ACCESS_TOKEN_TTL_SECONDS

            db.save_access_token(
                conn,
                access_token,
                client.client_id,
                authorization_code.scopes,
                authorization_code.resource,
                access_expires_at,
            )
            db.save_refresh_token(conn, refresh_token, client.client_id, authorization_code.scopes, None)

        return OAuthToken(
            access_token=access_token,
            token_type="Bearer",
            expires_in=ACCESS_TOKEN_TTL_SECONDS,
            scope=" ".join(authorization_code.scopes),
            refresh_token=refresh_token,
        )

    # ---- refresh tokens ----

    async def load_refresh_token(
        self, client: OAuthClientInformationFull, refresh_token: str
    ) -> RefreshToken | None:
        with db.connect() as conn:
            row = db.get_refresh_token(conn, refresh_token)
        if row is None or row["client_id"] != client.client_id:
            return None
        return RefreshToken(
            token=row["refresh_token"],
            client_id=row["client_id"],
            scopes=json.loads(row["scopes"]),
            expires_at=row["expires_at"],
        )

    async def exchange_refresh_token(
        self,
        client: OAuthClientInformationFull,
        refresh_token: RefreshToken,
        scopes: list[str],
    ) -> OAuthToken:
        with db.connect() as conn:
            db.delete_refresh_token(conn, refresh_token.token)

            new_access_token = secrets.token_urlsafe(32)
            new_refresh_token = secrets.token_urlsafe(32)
            access_expires_at = time.time() + ACCESS_TOKEN_TTL_SECONDS

            db.save_access_token(conn, new_access_token, client.client_id, scopes, None, access_expires_at)
            db.save_refresh_token(conn, new_refresh_token, client.client_id, scopes, None)

        return OAuthToken(
            access_token=new_access_token,
            token_type="Bearer",
            expires_in=ACCESS_TOKEN_TTL_SECONDS,
            scope=" ".join(scopes),
            refresh_token=new_refresh_token,
        )

    # ---- access tokens ----

    async def load_access_token(self, token: str) -> AccessToken | None:
        with db.connect() as conn:
            row = db.get_access_token(conn, token)
            if row is None:
                return None
            if row["expires_at"] is not None and row["expires_at"] < time.time():
                db.delete_access_token(conn, token)
                return None
        return AccessToken(
            token=row["access_token"],
            client_id=row["client_id"],
            scopes=json.loads(row["scopes"]),
            expires_at=int(row["expires_at"]) if row["expires_at"] is not None else None,
            resource=row["resource"],
        )

    async def revoke_token(self, token: AccessToken | RefreshToken) -> None:
        with db.connect() as conn:
            if isinstance(token, AccessToken):
                db.delete_access_token(conn, token.token)
            else:
                db.delete_refresh_token(conn, token.token)
