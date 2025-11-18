# Diet / Meal Log MCP Server

食事ログを管理するMCP (Model Context Protocol) サーバーです。

## 機能

- `add_meal`: 食事ログを追加
- `get_daily_summary`: 指定日の食事ログと合計カロリーを取得
- `get_week_summary`: 指定週の食事ログと合計カロリーを取得

## 必要な環境

- Python 3.11以上
- uv (推奨) または pip

## セットアップ

### 1. uvを使う方法（推奨）

uvは高速なPythonパッケージマネージャーです。

```bash
# uvのインストール
curl -LsSf https://astral.sh/uv/install.sh | sh

# 仮想環境の作成（Python 3.11を自動ダウンロード）
uv venv --python 3.11

# 仮想環境の有効化
source .venv/bin/activate

# 依存関係のインストール
uv pip install -r requirements.txt
```

### 2. pipを使う方法

```bash
# Python 3.11以上がインストールされていることを確認
python --version

# 仮想環境の作成
python -m venv .venv

# 仮想環境の有効化
source .venv/bin/activate

# 依存関係のインストール
pip install -r requirements.txt
```

## 使い方

このサーバーは2つのモードで動作します：

### モード1: ローカルモード（stdio）

Claude Desktopなどのローカルクライアント向け。

```bash
# 仮想環境を有効化
source .venv/bin/activate

# stdioモードで起動（デフォルト）
python server.py
```

#### Claude Desktopでの設定例

`~/Library/Application Support/Claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "diet-mcp": {
      "command": "/Users/soichiro.inatani/src/diet-mcp/.venv/bin/python",
      "args": ["/Users/soichiro.inatani/src/diet-mcp/server.py"],
      "env": {}
    }
  }
}
```

### モード2: ネットワークモード（SSE）

別デバイスからアクセスする場合。

```bash
# 仮想環境を有効化
source .venv/bin/activate

# SSEモードで起動（ネットワーク経由）
python server.py --sse
```

サーバーは `http://0.0.0.0:8000` で起動します。

#### 他のデバイスからの接続

1. **サーバーのIPアドレスを確認**

```bash
ifconfig | grep "inet " | grep -v 127.0.0.1
# 例: inet 192.168.0.184
```

2. **クライアント側の設定**

Claude Desktopの設定ファイル `~/Library/Application Support/Claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "diet-mcp-remote": {
      "url": "http://192.168.0.184:8000/sse",
      "transport": "sse"
    }
  }
}
```

**注意事項：**
- サーバーとクライアントが同じネットワーク内にある必要があります
- ファイアウォールでポート8000を開放してください
- インターネット経由でアクセスする場合は、適切なセキュリティ対策（認証、HTTPS化など）が必要です

### データの保存

食事ログは `~/diet-mcp-meals.json` に保存されます。

## 開発

### プロジェクト構成

```
diet-mcp/
├── server.py           # MCPサーバー本体
├── meals.json          # 食事ログデータ（自動生成）
├── requirements.txt    # Python依存関係
├── .python-version     # Pythonバージョン指定
├── .venv/             # 仮想環境（git管理外）
└── README.md          # このファイル
```

### チーム開発での環境共有

1. `.python-version` でPythonバージョンを固定
2. `requirements.txt` で依存関係を固定
3. `.venv/` はgit管理から除外（.gitignoreに追加）

```bash
# 新しいメンバーがリポジトリをクローンしたら
git clone <repository-url>
cd diet-mcp

# 環境構築
uv venv --python 3.11
source .venv/bin/activate
uv pip install -r requirements.txt

# サーバー起動
python server.py
```

## ライセンス

このプロジェクトは自由に使用できます。
