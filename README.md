# Diet / Meal Log MCP Server

食事ログを管理するMCP (Model Context Protocol) サーバー。ChatGPT (モバイル含む) のカスタムコネクタから使えるように、Streamable HTTP + OAuth 2.1 (動的クライアント登録 + PKCE) で常時稼働する構成にしています。

## 機能

- `add_meal`: 食事ログを1件追加(タンパク質・脂質・炭水化物は任意)。食事1件につき1回呼び出す想定(1日分をまとめて1回で記録しない)
- `update_meal`: 既存の食事ログを部分更新(idはget_daily_summary等の結果から取得)
- `delete_meal`: 食事ログを1件削除
- `get_daily_summary`: 指定日の食事ログ・合計カロリー・栄養素内訳・(設定していれば)目標カロリーとの差分を取得
- `get_week_summary`: 指定週(月曜始まり)の同様のサマリ
- `set_calorie_goal`: 1日の目標摂取カロリーを設定

データは SQLite (`DIET_MCP_DB_PATH`、デフォルト `~/.diet-mcp/diet-mcp.db`) に保存されます。スキーマ変更(栄養素フィールド追加等)は起動時に既存DBへ自動マイグレーションされます。

## アーキテクチャ

- transport: Streamable HTTP のみ (stdio/SSEは廃止 — Claude Desktopでのローカル利用は今回のスコープ外)
- 認証: OAuth 2.1 (認可コード + PKCE + 動的クライアント登録)。ChatGPT Connectorsが要求する`/.well-known/oauth-authorization-server`と`/.well-known/oauth-protected-resource/mcp`を自前で実装(`src/diet_mcp/oauth_provider.py`)。単一ユーザー向けなので第三者IdPには委譲せず、このサーバー自身が認可サーバーになる
- ログイン: `/authorize`からリダイレクトされる`/login`で、`DIET_MCP_API_KEY`をそのままログインパスワードとして入力し承認する(アカウント所有者が1人である前提の簡略化)
- ストレージ: SQLite。旧バージョンのJSONファイルは `legacy/` に退避済み

## ローカル実行

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

export DIET_MCP_API_KEY=$(openssl rand -hex 32)     # /loginのパスワードにもなる
export DIET_MCP_ISSUER_URL=http://127.0.0.1:8000    # このサーバーの公開URL(本番ではhttps必須)
python -m diet_mcp.server   # http://0.0.0.0:8000/mcp
```

テスト:

```bash
pytest tests/ -q
```

## デプロイ (Fly.io)

HTTPSで常時アクセス可能な場所に置く必要があるため、Fly.ioを想定した`Dockerfile`/`fly.toml`を用意しています(他のホスティングでも`Dockerfile`はそのまま使えます)。**以下は実行前に内容を確認してください。アプリ作成・ボリューム作成・シークレット設定はすべて実際にFlyのアカウント/課金に影響します。**

```bash
# flyctl未インストールの場合
curl -L https://fly.io/install.sh | sh

fly launch --no-deploy         # fly.tomlのapp名が既に埋まっているので確認・調整
fly volumes create diet_mcp_data --size 1 --region nrt
fly secrets set DIET_MCP_API_KEY=$(openssl rand -hex 32)
fly deploy
```

`fly.toml`の`[env] DIET_MCP_ISSUER_URL`をデプロイ先の実際のURL(例: `https://diet-mcp.fly.dev`)に合わせてください。

`fly.toml` は `min_machines_running = 0` にしているため、アイドル時は完全停止しコスト最小化されますが、初回アクセス時にコールドスタートの遅延が発生します。気になる場合は `min_machines_running = 1` に変更してください。

## ChatGPTへの接続

1. ChatGPT (Plus/Pro/Team/Enterprise) の設定 → Connectors → カスタムコネクタを追加
2. Server URL に `https://<app-name>.fly.dev/mcp` を入力
3. 認証は「OAuth」を選択。サーバーが`/.well-known/oauth-authorization-server`と`/.well-known/oauth-protected-resource/mcp`を公開しているので、認可URL・トークンURL・登録URL・リソースはChatGPT側が自動検出する(手入力は不要)
4. コネクタ追加後、ブラウザで`/login`ページが開くので `DIET_MCP_API_KEY` の値をパスワードとして入力して許可する
5. モバイルアプリでは、Web/デスクトップで一度コネクタを追加すればアカウント側の設定として反映され、モバイルからも同じコネクタが使えます

## 既存データの移行

旧バージョンでは `~/diet-mcp-meals.json` にデータを保存していました(今回の環境には実データはありませんでした)。もしデータがあれば:

```bash
python scripts/migrate_json_to_sqlite.py ~/diet-mcp-meals.json
```

## プロジェクト構成

```
diet-mcp/
├── src/diet_mcp/
│   ├── server.py         # FastMCPアプリ + AuthSettings + entrypoint
│   ├── tools.py          # add_meal / update_meal / delete_meal / get_daily_summary / get_week_summary / set_calorie_goal
│   ├── db.py             # SQLiteアクセス層 (meals + OAuth状態)
│   ├── models.py         # Mealデータクラス
│   ├── oauth_provider.py # OAuthAuthorizationServerProvider実装(単一ユーザー向け)
│   ├── auth.py           # /loginページ(パスワード確認→認可コード発行)
│   └── pkce_compat.py    # PKCE省略クライアント(ChatGPT Connectors)向けの互換ミドルウェア
├── scripts/migrate_json_to_sqlite.py
├── tests/test_tools.py
├── legacy/               # 旧stdio/SSE版 (server.py, web_server.py等) を参考用に保存
├── Dockerfile
├── fly.toml
└── pyproject.toml
```
