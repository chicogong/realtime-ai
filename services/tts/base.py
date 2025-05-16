import asyncio
import logging
from abc import ABC, abstractmethod
from typing import List, Optional, Set

from fastapi import WebSocket

logger = logging.getLogger(__name__)


class BaseTTSService(ABC):
    """TTS服务的抽象基类，定义所有TTS服务必须实现的接口"""

    def __init__(self) -> None:
        """初始化TTS服务"""
        self.session_id = None

    def set_session_id(self, session_id: str) -> None:
        """设置会话ID

        Args:
            session_id: 会话唯一标识符
        """
        self.session_id = session_id

    @abstractmethod
    async def synthesize_text(self, text: str, websocket: WebSocket, is_first: bool = False) -> None:
        """将文本合成为语音并发送到客户端

        Args:
            text: 要合成的文本
            websocket: WebSocket连接
            is_first: 是否是本次响应的第一句话
        """
        pass

    @abstractmethod
    async def interrupt(self) -> bool:
        """中断当前的语音合成

        Returns:
            是否成功中断
        """
        pass

    @abstractmethod
    async def close(self) -> None:
        """关闭TTS服务，释放资源"""
        pass
