import asyncio
import logging
import uvicorn

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse
from openai import AsyncOpenAI

from config import Config
from models.session import SessionState, sessions
from services.websocket.handler import handle_websocket_connection, cleanup_inactive_sessions, stop_tts_and_clear_queues, process_final_transcript
from services.tts import close_all_tts_services

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(funcName)s - %(message)s'
)
logger = logging.getLogger(__name__)

# 初始化FastAPI应用
app = FastAPI(title="实时AI对话API")

# 配置OpenAI客户端
openai_client = AsyncOpenAI(
    api_key=Config.OPENAI_API_KEY,
    base_url=Config.OPENAI_BASE_URL if Config.OPENAI_BASE_URL else None
)

# WebSocket路由
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    """WebSocket连接终端点，处理与客户端的实时通信"""
    await handle_websocket_connection(websocket)

# 静态页面路由
@app.get("/", response_class=HTMLResponse)
async def get_root() -> str:
    """返回主页HTML"""
    with open("static/index.html", "r", encoding="utf-8") as f:
        return f.read()

# 健康检查端点
@app.get("/health")
async def health_check() -> dict:
    """健康检查端点"""
    return {"status": "ok"}

# 应用启动时的事件处理
@app.on_event("startup")
async def startup_event() -> None:
    """应用启动时执行的操作"""
    # 启动会话清理任务
    asyncio.create_task(cleanup_inactive_sessions())
    logger.info("应用已启动，正在监听WebSocket连接...")

# 应用关闭时的事件处理
@app.on_event("shutdown")
async def shutdown_event() -> None:
    """应用关闭时执行的操作"""
    # 关闭TTS资源
    await close_all_tts_services()
    logger.info("应用已关闭")

# 服务静态文件
app.mount("/static", StaticFiles(directory="static"), name="static")

if __name__ == "__main__":
    # 启动服务器
    uvicorn.run("app:app", host="127.0.0.1", port=8000, reload=True)