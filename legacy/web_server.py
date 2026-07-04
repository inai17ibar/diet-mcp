#!/usr/bin/env python
"""
Diet MCP Server - Web API版
モバイルブラウザからアクセスできるREST APIとシンプルなWeb UI
"""
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Optional
from datetime import date
import uvicorn

# サーバーモジュールをインポート
from server import add_meal, get_daily_summary, get_week_summary

app = FastAPI(title="Diet MCP Web API")

# CORS設定（モバイルからのアクセスを許可）
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# リクエストモデル
class MealRequest(BaseModel):
    date_str: str
    time_str: str
    description: str
    calories: float
    tags: Optional[List[str]] = None

@app.get("/", response_class=HTMLResponse)
async def index():
    """シンプルなWeb UI"""
    return """
    <!DOCTYPE html>
    <html lang="ja">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>食事ログ</title>
        <style>
            body {
                font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
                max-width: 600px;
                margin: 0 auto;
                padding: 20px;
                background: #f5f5f5;
            }
            .card {
                background: white;
                border-radius: 12px;
                padding: 20px;
                margin-bottom: 20px;
                box-shadow: 0 2px 8px rgba(0,0,0,0.1);
            }
            h1 { color: #333; margin-top: 0; }
            h2 { color: #666; font-size: 1.2em; }
            input, textarea, button {
                width: 100%;
                padding: 12px;
                margin: 8px 0;
                border: 1px solid #ddd;
                border-radius: 8px;
                font-size: 16px;
                box-sizing: border-box;
            }
            button {
                background: #007AFF;
                color: white;
                border: none;
                cursor: pointer;
                font-weight: 600;
            }
            button:hover { background: #0051D5; }
            .meal-item {
                padding: 12px;
                margin: 8px 0;
                background: #f8f8f8;
                border-radius: 8px;
            }
            .total {
                font-size: 1.3em;
                font-weight: bold;
                color: #007AFF;
                margin: 16px 0;
            }
            .tag {
                display: inline-block;
                background: #E5E5EA;
                padding: 4px 8px;
                border-radius: 4px;
                font-size: 0.9em;
                margin: 4px 4px 0 0;
            }
        </style>
    </head>
    <body>
        <div class="card">
            <h1>🍽️ 食事ログ</h1>
            <form id="mealForm">
                <input type="date" id="date" required>
                <input type="time" id="time" required>
                <input type="text" id="description" placeholder="食事内容" required>
                <input type="number" id="calories" placeholder="カロリー (kcal)" required>
                <input type="text" id="tags" placeholder="タグ (カンマ区切り)">
                <button type="submit">記録</button>
            </form>
        </div>

        <div class="card">
            <h2>今日の食事</h2>
            <button onclick="loadToday()">読み込み</button>
            <div id="todayResult"></div>
        </div>

        <div class="card">
            <h2>週の集計</h2>
            <button onclick="loadWeek()">読み込み</button>
            <div id="weekResult"></div>
        </div>

        <script>
            // 今日の日付をデフォルトに設定
            document.getElementById('date').valueAsDate = new Date();
            document.getElementById('time').value = new Date().toTimeString().slice(0,5);

            // 食事を追加
            document.getElementById('mealForm').onsubmit = async (e) => {
                e.preventDefault();
                const tags = document.getElementById('tags').value
                    .split(',')
                    .map(t => t.trim())
                    .filter(t => t);

                const response = await fetch('/api/meal', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({
                        date_str: document.getElementById('date').value,
                        time_str: document.getElementById('time').value,
                        description: document.getElementById('description').value,
                        calories: parseFloat(document.getElementById('calories').value),
                        tags: tags.length > 0 ? tags : null
                    })
                });

                if (response.ok) {
                    alert('記録しました！');
                    document.getElementById('description').value = '';
                    document.getElementById('calories').value = '';
                    document.getElementById('tags').value = '';
                    loadToday();
                }
            };

            // 今日の食事を読み込み
            async function loadToday() {
                const today = new Date().toISOString().split('T')[0];
                const response = await fetch(`/api/daily/${today}`);
                const data = await response.json();

                let html = `<div class="total">合計: ${data.total_calories} kcal</div>`;
                data.meals.forEach(meal => {
                    html += `
                        <div class="meal-item">
                            <strong>${meal.time}</strong> - ${meal.description}
                            <br>${meal.calories} kcal
                            ${meal.tags.map(t => `<span class="tag">${t}</span>`).join('')}
                        </div>
                    `;
                });
                document.getElementById('todayResult').innerHTML = html || '<p>まだ記録がありません</p>';
            }

            // 週の集計を読み込み
            async function loadWeek() {
                const today = new Date().toISOString().split('T')[0];
                const response = await fetch(`/api/weekly/${today}`);
                const data = await response.json();

                let html = `<div class="total">週合計: ${data.week_total_calories} kcal</div>`;
                html += `<p>${data.start_date} 〜 ${data.end_date}</p>`;
                data.daily.forEach(day => {
                    if (day.meals.length > 0) {
                        html += `
                            <div class="meal-item">
                                <strong>${day.date}</strong>: ${day.total_calories} kcal (${day.meals.length}件)
                            </div>
                        `;
                    }
                });
                document.getElementById('weekResult').innerHTML = html;
            }

            // 初期読み込み
            loadToday();
        </script>
    </body>
    </html>
    """

@app.post("/api/meal")
async def add_meal_api(meal: MealRequest):
    """食事を追加"""
    try:
        result = add_meal(
            date_str=meal.date_str,
            time_str=meal.time_str,
            description=meal.description,
            calories=meal.calories,
            tags=meal.tags
        )
        return result
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.get("/api/daily/{date_str}")
async def get_daily_api(date_str: str):
    """日次サマリー"""
    try:
        result = get_daily_summary(date_str)
        return result
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.get("/api/weekly/{date_str}")
async def get_weekly_api(date_str: str):
    """週次サマリー"""
    try:
        result = get_week_summary(date_str)
        return result
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

if __name__ == "__main__":
    import sys
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8080

    print(f"🌐 Starting Diet MCP Web Server")
    print(f"📱 Mobile Access: http://0.0.0.0:{port}")
    print(f"📝 Data file: ~/diet-mcp-meals.json")
    print(f"\n💡 Access from your phone's browser using your computer's IP address")

    uvicorn.run(app, host="0.0.0.0", port=port)
