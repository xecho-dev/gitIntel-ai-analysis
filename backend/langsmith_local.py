"""本地 LangSmith Studio - 简单的追踪查看器。

启动命令: python -m langsmith_local
访问地址: http://localhost:2024

注意：这是一个简化版本，完整功能请使用 LangSmith 云端 https://smith.langchain.com/
"""
import json
import logging
import os
from datetime import datetime, timedelta

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, Query
from fastapi.responses import HTMLResponse

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("langsmith_local")

app = FastAPI(title="LangSmith Studio Local")

LANGSMITH_API_KEY = os.getenv("LANGSMITH_API_KEY", "").strip()
LANGSMITH_ENDPOINT = os.getenv("LANGSMITH_ENDPOINT", "https://api.smith.langchain.com")
LANGSMITH_PROJECT = os.getenv("LANGSMITH_PROJECT", "default")


def _fetch_traces(limit: int = 20, status_filter: str = "all") -> list[dict]:
    """从 LangSmith API 获取最近的追踪记录。"""
    if not LANGSMITH_API_KEY:
        return []

    headers = {
        "Authorization": f"Bearer {LANGSMITH_API_KEY}",
        "Content-Type": "application/json",
    }

    # 计算时间范围（最近 24 小时）
    end_time = datetime.now()
    start_time = end_time - timedelta(hours=24)

    params = {
        "projectName": LANGSMITH_PROJECT,
        "limit": limit,
        "startTime": start_time.isoformat(),
        "endTime": end_time.isoformat(),
    }

    if status_filter == "completed":
        params["status"] = "completed"
    elif status_filter == "error":
        params["status"] = "error"

    try:
        response = httpx.get(
            f"{LANGSMITH_ENDPOINT}/api/v1/runs",
            headers=headers,
            params=params,
            timeout=30,
        )
        if response.status_code == 200:
            data = response.json()
            return data.get("runs", [])
        else:
            logger.error(f"API 错误: {response.status_code} - {response.text}")
            return []
    except Exception as e:
        logger.error(f"获取追踪失败: {e}")
        return []


@app.get("/", response_class=HTMLResponse)
async def index():
    """LangSmith Studio 本地调试界面。"""
    traces = _fetch_traces(limit=50)

    # 统计信息
    total = len(traces)
    errors = sum(1 for t in traces if t.get("status") == "error")
    completed = sum(1 for t in traces if t.get("status") == "completed")

    traces_html = ""
    for trace in traces:
        trace_id = trace.get("id", "")[:12] + "..."
        trace_name = trace.get("name", "unnamed")
        status = trace.get("status", "unknown")
        created_at = trace.get("start_time", "")[:19] if trace.get("start_time") else ""

        # Token 统计
        token_usage = trace.get("token_usage", {})
        total_tokens = token_usage.get("total_tokens", 0)

        status_class = {
            "completed": "status-success",
            "error": "status-error",
            "in_progress": "status-progress",
        }.get(status, "status-unknown")

        traces_html += f"""
        <tr>
            <td><code>{trace_id}</code></td>
            <td>{trace_name}</td>
            <td><span class="{status_class}">{status}</span></td>
            <td>{created_at}</td>
            <td>{total_tokens:,}</td>
            <td>
                <a href="https://smith.langchain.com/projects/{LANGSMITH_PROJECT}/runs/{trace.get('id', '')}"
                   target="_blank" class="btn-small">查看</a>
            </td>
        </tr>
        """

    if not traces_html:
        traces_html = """
        <tr>
            <td colspan="6" style="text-align: center; color: #888;">
                暂无追踪记录。请先调用一次分析接口。
            </td>
        </tr>
        """

    return HTMLResponse(content=f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>LangSmith Studio - 本地追踪查看器</title>
        <style>
            * {{ box-sizing: border-box; margin: 0; padding: 0; }}
            body {{
                font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
                background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
                color: #eee;
                min-height: 100vh;
                padding: 20px;
            }}
            .container {{ max-width: 1400px; margin: 0 auto; }}
            h1 {{
                color: #4ade80;
                margin-bottom: 5px;
                display: flex;
                align-items: center;
                gap: 10px;
            }}
            .subtitle {{
                color: #888;
                margin-bottom: 30px;
            }}
            .stats {{
                display: grid;
                grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
                gap: 15px;
                margin-bottom: 30px;
            }}
            .stat-card {{
                background: #16213e;
                border-radius: 12px;
                padding: 20px;
                border: 1px solid #2d3a5a;
            }}
            .stat-card .value {{
                font-size: 2em;
                font-weight: bold;
                color: #60a5fa;
            }}
            .stat-card .label {{
                color: #888;
                font-size: 0.9em;
            }}
            .stat-card.success .value {{ color: #4ade80; }}
            .stat-card.error .value {{ color: #ef4444; }}
            .actions {{
                display: flex;
                gap: 15px;
                margin-bottom: 20px;
                flex-wrap: wrap;
            }}
            .actions a {{
                padding: 10px 20px;
                background: #4ade80;
                color: #1a1a2e;
                text-decoration: none;
                border-radius: 8px;
                font-weight: bold;
                transition: transform 0.2s;
            }}
            .actions a:hover {{ transform: scale(1.05); }}
            .actions .secondary {{
                background: #2d3a5a;
                color: #eee;
            }}
            table {{
                width: 100%;
                border-collapse: collapse;
                background: #16213e;
                border-radius: 12px;
                overflow: hidden;
            }}
            th {{
                background: #0f172a;
                padding: 15px;
                text-align: left;
                font-weight: 600;
                color: #60a5fa;
            }}
            td {{
                padding: 12px 15px;
                border-top: 1px solid #2d3a5a;
            }}
            tr:hover {{ background: #1e2d4a; }}
            .status-success {{ color: #4ade80; }}
            .status-error {{ color: #ef4444; }}
            .status-progress {{ color: #fbbf24; }}
            .status-unknown {{ color: #888; }}
            .btn-small {{
                padding: 4px 12px;
                background: #60a5fa;
                color: #1a1a2e;
                text-decoration: none;
                border-radius: 4px;
                font-size: 0.85em;
            }}
            code {{
                background: #0f172a;
                padding: 2px 6px;
                border-radius: 4px;
                color: #60a5fa;
            }}
            .warning {{
                background: #fbbf24;
                color: #1a1a2e;
                padding: 15px 20px;
                border-radius: 8px;
                margin-bottom: 20px;
            }}
        </style>
    </head>
    <body>
        <div class="container">
            <h1>LangSmith Studio</h1>
            <p class="subtitle">本地追踪查看器 | 项目: {LANGSMITH_PROJECT}</p>

            <div class="stats">
                <div class="stat-card">
                    <div class="value">{total}</div>
                    <div class="label">总追踪数</div>
                </div>
                <div class="stat-card success">
                    <div class="value">{completed}</div>
                    <div class="label">已完成</div>
                </div>
                <div class="stat-card error">
                    <div class="value">{errors}</div>
                    <div class="label">错误</div>
                </div>
            </div>

            <div class="actions">
                <a href="https://smith.langchain.com/" target="_blank">
                    LangSmith 云端
                </a>
                <a href="https://smith.langchain.com/projects/{LANGSMITH_PROJECT}" target="_blank" class="secondary">
                    项目页面
                </a>
                <a href="/refresh" class="secondary">刷新</a>
            </div>

            {"<div class='warning'>⚠️ LANGSMITH_API_KEY 未配置，无法获取追踪记录</div>" if not LANGSMITH_API_KEY else ""}

            <table>
                <thead>
                    <tr>
                        <th>Trace ID</th>
                        <th>名称</th>
                        <th>状态</th>
                        <th>开始时间</th>
                        <th>Token 消耗</th>
                        <th>操作</th>
                    </tr>
                </thead>
                <tbody>
                    {traces_html}
                </tbody>
            </table>
        </div>
    </body>
    </html>
    """)


@app.get("/refresh", response_class=HTMLResponse)
async def refresh():
    """刷新追踪列表。"""
    return await index()


if __name__ == "__main__":
    import uvicorn
    print(f"启动 LangSmith Studio 本地追踪查看器...")
    print(f"访问地址: http://localhost:2024")
    print(f"云端地址: https://smith.langchain.com/projects/{LANGSMITH_PROJECT}")
    uvicorn.run(app, host="0.0.0.0", port=2024)
