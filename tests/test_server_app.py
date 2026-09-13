"""組み上がったASGIアプリの疎通テスト。

tools/dbのテストだけではSDKのAPI変更を検出できず、mcp 2.xでFastMCPが
消えたことにデプロイ時まで気づけなかった。ここではimportが通ること、
OAuthメタデータとREST APIが応答すること、そして本番のHostヘッダーで
/mcp がDNSリバインディング保護に弾かれないことを確認する。
"""

import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

# server は import 時に issuer と APIキーを要求するので、先に環境を作る
ISSUER = "https://diet-mcp.fly.dev"
API_KEY = "test-api-key"
os.environ.setdefault("DIET_MCP_ISSUER_URL", ISSUER)
os.environ.setdefault("DIET_MCP_API_KEY", API_KEY)
os.environ.setdefault("DIET_MCP_DB_PATH", str(Path(tempfile.mkdtemp()) / "test.db"))

import json
import time

import pytest
from starlette.testclient import TestClient

from diet_mcp import db
from diet_mcp.oauth_provider import SCOPE
from diet_mcp.server import app

ACCESS_TOKEN = "test-access-token"


def _seed_oauth_token() -> None:
    """認可フローを通さずに、有効なアクセストークンをDBへ直接用意する。"""
    with db.connect() as conn:
        db.save_oauth_client(
            conn,
            "test-client",
            json.dumps(
                {
                    "client_id": "test-client",
                    "redirect_uris": ["https://example.com/cb"],
                    "grant_types": ["authorization_code", "refresh_token"],
                    "response_types": ["code"],
                    "token_endpoint_auth_method": "none",
                    "scope": SCOPE,
                }
            ),
        )
        db.save_access_token(
            conn, ACCESS_TOKEN, "test-client", [SCOPE], f"{ISSUER}/mcp", time.time() + 3600
        )


def _sse_json(response) -> dict:
    """SSE形式(event: message / data: {...})のレスポンスからJSONを取り出す。"""
    for line in response.text.splitlines():
        if line.startswith("data:"):
            return json.loads(line[len("data:") :].strip())
    raise AssertionError(f"JSONが取り出せない: {response.text[:200]}")


@pytest.fixture(scope="module")
def client():
    """アプリのライフスパンは1インスタンスにつき1回しか起動できないので使い回す。

    本番と同じHostで叩く（TestClient既定の testserver ではDNSリバインディング
    保護の有無を検出できない）。
    """
    _seed_oauth_token()
    with TestClient(app, base_url=ISSUER) as c:
        yield c


def test_oauth_authorization_server_metadata(client):
    """ChatGPTコネクタが最初に読むメタデータ。"""
    response = client.get("/.well-known/oauth-authorization-server")
    assert response.status_code == 200
    body = response.json()
    assert body["issuer"].rstrip("/") == ISSUER
    assert "registration_endpoint" in body  # 動的クライアント登録が有効


def test_protected_resource_metadata(client):
    response = client.get("/.well-known/oauth-protected-resource/mcp")
    assert response.status_code == 200


def test_login_page_is_served(client):
    assert client.get("/login").status_code == 200


def test_rest_api_requires_bearer(client):
    assert client.get("/api/summary/daily").status_code == 401
    assert client.get("/api/summary/week").status_code == 401


def test_rest_api_with_bearer(client):
    headers = {"Authorization": f"Bearer {API_KEY}"}
    daily = client.get("/api/summary/daily", headers=headers)
    week = client.get("/api/summary/week", headers=headers)
    assert daily.status_code == 200
    assert week.status_code == 200
    assert len(week.json()["daily"]) == 7


MCP_HEADERS = {
    "Accept": "application/json, text/event-stream",
    "Content-Type": "application/json",
    "Authorization": f"Bearer {ACCESS_TOKEN}",
}


def test_mcp_endpoint_requires_auth(client):
    response = client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        headers={"Accept": "application/json, text/event-stream"},
    )
    assert response.status_code == 401
    assert "www-authenticate" in {k.lower() for k in response.headers}


def test_mcp_initialize_succeeds_with_production_host(client):
    """本番のHostヘッダーでMCPハンドシェイクが成立すること。

    mcp 2.xの streamable_http_app(host=...) を既定の 127.0.0.1 のままにすると
    DNSリバインディング保護がlocalhost限定で自動有効になり、本番
    (Host: diet-mcp.fly.dev)からのリクエストが 421 Misdirected Request で
    弾かれる。認証を通さないと401で手前で止まりこの層まで届かないため、
    このテストは必ずトークン付きで行うこと。
    """
    response = client.post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "test", "version": "1"},
            },
        },
        headers=MCP_HEADERS,
    )
    assert response.status_code == 200, f"{response.status_code}: {response.text[:200]}"
    assert "result" in _sse_json(response)


def test_mcp_exposes_the_expected_tools(client):
    """ChatGPTコネクタが呼ぶツールが登録されていること。"""
    response = client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
        headers=MCP_HEADERS,
    )
    assert response.status_code == 200, f"{response.status_code}: {response.text[:200]}"
    names = {t["name"] for t in _sse_json(response)["result"]["tools"]}
    assert names == {
        "add_meal",
        "update_meal",
        "delete_meal",
        "get_daily_summary",
        "get_week_summary",
        "set_calorie_goal",
    }
