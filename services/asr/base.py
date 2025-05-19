import asyncio
from abc import ABC, abstractmethod
from typing import Optional

from fastapi import WebSocket
from loguru import logger


class BaseASRService(ABC):
    """Abstract base class for speech recognition services"""

    def __init__(self, language: str = "en-US") -> None:
        self.language = language
        self.is_recognizing = False
        self.websocket: Optional[WebSocket] = None
        self.session_id: str = ""
        self.loop: Optional[asyncio.AbstractEventLoop] = None
        self.last_partial_result = ""

    def set_websocket(self, websocket: WebSocket, loop: asyncio.AbstractEventLoop, session_id: str) -> None:
        """Set WebSocket connection and event loop"""
        self.websocket = websocket
        self.loop = loop
        self.session_id = session_id

    @abstractmethod
    async def start_recognition(self) -> None:
        """Start speech recognition"""
        pass

    @abstractmethod
    async def stop_recognition(self) -> None:
        """Stop speech recognition"""
        pass

    @abstractmethod
    def feed_audio(self, audio_chunk: bytes) -> None:
        """Process incoming audio data"""
        pass

    @abstractmethod
    def setup_handlers(self) -> None:
        """Setup event handlers"""
        pass

    async def send_partial_transcript(self, text: str) -> None:
        """Send partial recognition result"""
        if self.websocket and text.strip():
            await self.websocket.send_json(
                {"type": "partial_transcript", "content": text, "session_id": self.session_id}
            )

    async def send_final_transcript(self, text: str) -> None:
        """Send final recognition result"""
        if self.websocket and text.strip():
            await self.websocket.send_json({"type": "final_transcript", "content": text, "session_id": self.session_id})

    async def send_status(self, status: str) -> None:
        """Send status information"""
        if self.websocket:
            await self.websocket.send_json({"type": "status", "status": status, "session_id": self.session_id})

    async def send_error(self, error_message: str) -> None:
        """Send error message"""
        if self.websocket:
            await self.websocket.send_json({"type": "error", "message": error_message, "session_id": self.session_id})
