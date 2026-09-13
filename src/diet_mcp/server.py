from __future__ import annotations

import os

import uvicorn
from mcp.server.auth.settings import AuthSettings, ClientRegistrationOptions
from mcp.server.mcpserver import MCPServer

from diet_mcp import tools
from diet_mcp.auth import handle_login, require_api_key
from diet_mcp.health_export import (
    daily_summary,
    list_unsynced_meals,
    mark_all_meals_synced,
    mark_meals_synced,
    week_summary,
)
from diet_mcp.oauth_provider import SCOPE, DietMcpOAuthProvider
from diet_mcp.pkce_compat import OptionalPkceMiddleware


def _issuer_url() -> str:
    url = os.environ.get("DIET_MCP_ISSUER_URL")
    if not url:
        raise RuntimeError(
            "DIET_MCP_ISSUER_URL is not set (e.g. https://diet-mcp.fly.dev). "
            "It must be the public HTTPS URL this server is reachable at."
        )
    return url.rstrip("/")


issuer_url = _issuer_url()
require_api_key()  # fail fast if the login password isn't configured

def _port() -> int:
    return int(os.environ.get("PORT", os.environ.get("MCP_PORT", "8000")))


mcp = MCPServer(
    "Diet Meal Log Server",
    auth_server_provider=DietMcpOAuthProvider(issuer_url),
    auth=AuthSettings(
        issuer_url=issuer_url,
        resource_server_url=f"{issuer_url}/mcp",
        # mcp 3.0で既定がTrueになる。既存のアクセストークンにはresourceが
        # 入っていないものがあり、Trueにすると再認証が必要になるため、
        # 1.x時代と同じ挙動（監査しない）を明示して固定する
        validate_token_resource=False,
        required_scopes=[SCOPE],
        client_registration_options=ClientRegistrationOptions(
            enabled=True,
            valid_scopes=[SCOPE],
            default_scopes=[SCOPE],
        ),
    ),
)

mcp.tool()(tools.add_meal)
mcp.tool()(tools.update_meal)
mcp.tool()(tools.delete_meal)
mcp.tool()(tools.get_daily_summary)
mcp.tool()(tools.get_week_summary)
mcp.tool()(tools.set_calorie_goal)
mcp.custom_route("/login", methods=["GET", "POST"])(handle_login)
mcp.custom_route("/api/summary/daily", methods=["GET"])(daily_summary)
mcp.custom_route("/api/summary/week", methods=["GET"])(week_summary)
mcp.custom_route("/api/meals/unsynced", methods=["GET"])(list_unsynced_meals)
mcp.custom_route("/api/meals/mark-synced", methods=["POST"])(mark_meals_synced)
mcp.custom_route("/api/meals/mark-all-synced", methods=["POST"])(mark_all_meals_synced)

# host はバインド先ではなくDNSリバインディング保護の判定に使われる。既定の
# "127.0.0.1" のままだとallowed_hostsがlocalhost限定で自動有効化され、
# 本番(Host: diet-mcp.fly.dev)への /mcp リクエストが弾かれる
app = OptionalPkceMiddleware(mcp.streamable_http_app(stateless_http=True, host="0.0.0.0"))


def main() -> None:
    uvicorn.run(app, host="0.0.0.0", port=_port())


if __name__ == "__main__":
    main()
