import asyncio
import sys
from contextlib import asynccontextmanager
from typing import AsyncGenerator, Dict, Any

import uvicorn
from fastapi import FastAPI, WebSocket
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from loguru import logger

from config import Config
from session import cleanup_inactive_sessions
from services.tts import close_all_tts_services
from websocket.handler import handle_websocket_connection


def configure_logger() -> None:
    """Configure loguru logger with appropriate format and level"""
    logger.remove()
    logger.add(
        sys.stderr,
        format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan> - <level>{message}</level>",
        level="INFO",
        colorize=True,
    )


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan manager for startup and shutdown processes"""
    # Startup: Initialize background tasks
    cleanup_task = asyncio.create_task(cleanup_inactive_sessions())
    logger.info("Application started, listening for WebSocket connections")

    yield

    # Shutdown: Cleanup resources and cancel tasks
    await close_all_tts_services()
    cleanup_task.cancel()
    try:
        await cleanup_task
    except asyncio.CancelledError:
        pass
    logger.info("Application shut down")


def create_app() -> FastAPI:
    """Create and configure the FastAPI application"""
    app = FastAPI(title="Realtime AI Chat API", lifespan=lifespan)
    
    # Register routes
    app.add_api_websocket_route("/ws", websocket_endpoint)
    app.add_api_route("/", get_root, response_class=HTMLResponse)
    app.add_api_route("/health", health_check)
    
    # Serve static files
    app.mount("/static", StaticFiles(directory="static"), name="static")
    
    return app


async def websocket_endpoint(websocket: WebSocket) -> None:
    """WebSocket endpoint handling real-time communication with clients"""
    await handle_websocket_connection(websocket)


async def get_root() -> HTMLResponse:
    """Return the main page HTML"""
    with open("static/index.html", "r", encoding="utf-8") as f:
        return HTMLResponse(content=f.read())


async def health_check() -> Dict[str, str]:
    """Health check endpoint"""
    return {"status": "ok"}


# Configure logger
configure_logger()

# Initialize FastAPI app
app = create_app()

if __name__ == "__main__":
    uvicorn.run("app:app", host="127.0.0.1", port=8000, reload=True)
