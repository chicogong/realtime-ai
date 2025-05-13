import asyncio
import logging
from abc import ABC, abstractmethod
from typing import Optional, Any, Callable, Coroutine

from fastapi import WebSocket

logger = logging.getLogger(__name__)

class BaseASRService(ABC):
    """语音识别服务的抽象基类，定义所有ASR服务必须实现的接口"""
    
    def __init__(self, language: str = "zh-CN"):
        """初始化ASR服务
        
        Args:
            language: 识别语言代码
        """
        self.language = language
        self.is_recognizing = False
        self.websocket: Optional[WebSocket] = None
        self.session_id: str = ""
        self.loop: Optional[asyncio.AbstractEventLoop] = None
        self.last_partial_result = ""  # 最后的部分识别结果
    
    def set_websocket(self, websocket: WebSocket, loop: asyncio.AbstractEventLoop, session_id: str) -> None:
        """设置WebSocket连接和事件循环
        
        Args:
            websocket: WebSocket连接对象
            loop: 事件循环
            session_id: 会话ID
        """
        self.websocket = websocket
        self.loop = loop
        self.session_id = session_id
    
    @abstractmethod
    async def start_recognition(self) -> None:
        """开始语音识别"""
        pass
    
    @abstractmethod
    async def stop_recognition(self) -> None:
        """停止语音识别"""
        pass
    
    @abstractmethod
    def feed_audio(self, audio_chunk: bytes) -> None:
        """处理输入的音频数据
        
        Args:
            audio_chunk: 音频数据块
        """
        pass
    
    @abstractmethod
    def setup_handlers(self) -> None:
        """设置事件处理程序"""
        pass
    
    async def send_partial_transcript(self, text: str) -> None:
        """发送部分识别结果
        
        Args:
            text: 识别文本
        """
        if self.websocket and text.strip():
            await self.websocket.send_json({
                "type": "partial_transcript",
                "content": text,
                "session_id": self.session_id
            })
    
    async def send_final_transcript(self, text: str) -> None:
        """发送最终识别结果
        
        Args:
            text: 识别文本
        """
        if self.websocket and text.strip():
            await self.websocket.send_json({
                "type": "final_transcript",
                "content": text,
                "session_id": self.session_id
            })
    
    async def send_status(self, status: str) -> None:
        """发送状态信息
        
        Args:
            status: 状态描述
        """
        if self.websocket:
            await self.websocket.send_json({
                "type": "status",
                "status": status,
                "session_id": self.session_id
            })
    
    async def send_error(self, error_message: str) -> None:
        """发送错误信息
        
        Args:
            error_message: 错误消息
        """
        if self.websocket:
            await self.websocket.send_json({
                "type": "error",
                "message": error_message,
                "session_id": self.session_id
            }) 