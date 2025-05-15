import asyncio
import uvicorn
import sys
from loguru import logger
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse
from openai import AsyncOpenAI

from config import Config
from models.session import sessions
from services.websocket.handler import handle_websocket_connection, cleanup_inactive_sessions
from services.tts import close_all_tts_services

# Configure loguru
logger.remove()
logger.add(
    sys.stderr,
    format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan> - <level>{message}</level>",
    level="INFO",
    colorize=True
)

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup code
    cleanup_task = asyncio.create_task(cleanup_inactive_sessions())
    logger.info("Application started, listening for WebSocket connections")
    
    yield
    
    # Shutdown code
    await close_all_tts_services()
    cleanup_task.cancel()
    try:
        await cleanup_task
    except asyncio.CancelledError:
        pass
    logger.info("Application shut down")

# Initialize FastAPI app
app = FastAPI(title="Realtime AI Chat API", lifespan=lifespan)

# Configure OpenAI client
openai_client = AsyncOpenAI(
    api_key=Config.OPENAI_API_KEY,
    base_url=Config.OPENAI_BASE_URL if Config.OPENAI_BASE_URL else None
)

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    """WebSocket endpoint handling real-time communication with clients"""
    await handle_websocket_connection(websocket)

@app.get("/", response_class=HTMLResponse)
async def get_root() -> str:
    """Return the main page HTML"""
    with open("static/index.html", "r", encoding="utf-8") as f:
        return f.read()

@app.get("/health")
async def health_check() -> dict:
    """Health check endpoint"""
    return {"status": "ok"}

# Serve static files
app.mount("/static", StaticFiles(directory="static"), name="static")

if __name__ == "__main__":
    uvicorn.run("app:app", host="127.0.0.1", port=8000, reload=True)