from __future__ import annotations

import os

import uvicorn
from mcp.server.auth.settings import AuthSettings, ClientRegistrationOptions
from mcp.server.fastmcp import FastMCP

from diet_mcp import tools
from diet_mcp.auth import handle_login, require_api_key
from diet_mcp.health_export import list_unsynced_meals, mark_all_meals_synced, mark_meals_synced
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

mcp = FastMCP(
    "Diet Meal Log Server",
    host="0.0.0.0",
    port=int(os.environ.get("PORT", os.environ.get("MCP_PORT", "8000"))),
    stateless_http=True,
    auth_server_provider=DietMcpOAuthProvider(issuer_url),
    auth=AuthSettings(
        issuer_url=issuer_url,
        resource_server_url=f"{issuer_url}/mcp",
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
mcp.custom_route("/api/meals/unsynced", methods=["GET"])(list_unsynced_meals)
mcp.custom_route("/api/meals/mark-synced", methods=["POST"])(mark_meals_synced)
mcp.custom_route("/api/meals/mark-all-synced", methods=["POST"])(mark_all_meals_synced)

app = OptionalPkceMiddleware(mcp.streamable_http_app())


def main() -> None:
    uvicorn.run(app, host=mcp.settings.host, port=mcp.settings.port)


if __name__ == "__main__":
    main()
