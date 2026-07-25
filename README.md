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

## Apple ヘルスケアへの連携

HealthKitにはクラウドAPIが無く、サーバーから直接書き込むことはできない。そのため、iOSショートカットが仲介する構成にしている。

- `GET /api/meals/unsynced` — まだヘルスケアに反映していない食事ログ一覧(`Authorization: Bearer <DIET_MCP_API_KEY>`)
- `POST /api/meals/mark-all-synced` — 今ある未同期の食事を全部同期済みにする(ボディ不要)。ショートカット側でIDリストを組み立てる必要がなく最も簡単
- `POST /api/meals/mark-synced` — 個別に同期済みにしたい場合向け(body: `{"ids": ["<meal_id>", ...]}`)。通常は`mark-all-synced`で十分

この3つは`/mcp`のOAuthとは別に、`DIET_MCP_API_KEY`をそのままBearerトークンとして使う簡易認証。ショートカット側でOAuth/PKCEを組む必要がない。

### iOSショートカットの作り方(手動)

1. ショートカットアプリで新規オートメーション(例: 毎日22時、または手動実行)を作成
2. 「URLの内容を取得」で `GET https://<app-name>.fly.dev/api/meals/unsynced`、ヘッダーに `Authorization: Bearer <DIET_MCP_API_KEY>` を追加
3. 「辞書から値を取得」で`meals`配列を取り出し、「リストの各項目を繰り返す」で1件ずつ処理
4. 繰り返しの中で、各食事の`calories`(必要なら`protein_g`/`fat_g`/`carbs_g`も)を「辞書から値を取得」で取り出し、`date`+`time`を組み合わせてDate型に変換した上で、「ヘルスケアにサンプルを記録」で「摂取エネルギー」(および任意でタンパク質・脂質・炭水化物)に記録する。単位は`kcal`/`g`を明示的に選ぶこと(`cal`のままだと桁が変わってしまう)
5. 繰り返しの外(繰り返しの終了より下)に「URLの内容を取得」で `POST https://<app-name>.fly.dev/api/meals/mark-all-synced`、ヘッダーは同じBearer。ボディは不要(IDリストを組み立てる必要がない)

一度ヘルスケアに反映した食事は`synced_to_health`フラグが立ち、`update_meal`で内容を修正しても再エクスポートはされない(ヘルスケア側のサンプルは追記のみで上書きができないため、二重登録を避ける設計)。

### 二重記録の防止(claim方式)

ショートカットを短時間に連打すると、1回目の`mark-all-synced`が走る前に2回目が`unsynced`を取得してしまい、同じ食事がヘルスケアに二重記録される事故が起きた(2026-07-26に修正)。対策として:

- `GET /api/meals/unsynced` は、食事を返すと**同時に**該当行へclaim印(`health_claimed_at`)を付ける(`UPDATE ... RETURNING`で1文、並行リクエストでも取りこぼしなし)。claimから**10分(TTL)以内**の行は再配信されないため、連打しても2回目以降は空リストが返り、二重書き込みは起きない
- ヘルスケアに書き込まれないままTTLが過ぎた食事は自動的に再配信される(ショートカットが途中で失敗しても記録は失われない)
- `POST /api/meals/mark-all-synced` は**claim済みの行だけ**を同期済みにする。同期の最中にChatGPT側から追加された食事が、ヘルスケア未書き込みのまま同期済み扱いになる競合を防ぐ

## 周辺システムとの関係

食事記録の「本体」はこのサーバー(diet-mcp)で、データはFly.io Volume上のSQLiteに集約される。

```
ChatGPT ──(MCP / OAuth)──▶ diet-mcp (Fly.io / SQLite)
                                │
iOSショートカット ◀──(REST / Bearer)──┘
「カロリーをヘルスケアに記録」
      │
      ▼
Apple ヘルスケア
```

- **ChatGPT**: 記録の入力UI。会話からカロリー・PFCを概算して`add_meal`を呼ぶ
- **iOSショートカット**: ヘルスケアへの反映係(HealthKitにはクラウドAPIが無いため)
- **chatgpt-diet-app** (別リポジトリ、Railway: https://chatgpt-diet-app-production.up.railway.app/): Web UI・共有画像生成・投稿文生成を持つ別系統のフルスタックアプリ。名前は似ているが**日々の食事記録には使われていない**(2026-07-26時点で本番DBは0件)。将来的にSNS発信系(画像レンダリング・投稿)の役割を担う候補

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
│   ├── pkce_compat.py    # PKCE省略クライアント(ChatGPT Connectors)向けの互換ミドルウェア
│   └── health_export.py  # ヘルスケア連携用のREST API(/api/meals/unsynced, /mark-all-synced, /mark-synced)
├── scripts/migrate_json_to_sqlite.py
├── tests/test_tools.py
├── legacy/               # 旧stdio/SSE版 (server.py, web_server.py等) を参考用に保存
├── Dockerfile
├── fly.toml
└── pyproject.toml
```
