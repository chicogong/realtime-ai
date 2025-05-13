import logging
from abc import ABC, abstractmethod
from typing import AsyncGenerator, Dict, Any, List, Optional

logger = logging.getLogger(__name__)

class BaseLLMService(ABC):
    """LLM服务的抽象基类，定义所有LLM服务必须实现的接口"""
    
    def __init__(self):
        """初始化LLM服务"""
        pass
    
    @abstractmethod
    async def generate_response(self, text: str, system_prompt: Optional[str] = None) -> AsyncGenerator[str, None]:
        """生成文本响应
        
        Args:
            text: 用户输入文本
            system_prompt: 系统提示，用于设置AI助手的行为
            
        Returns:
            异步生成器，产生文本片段
        """
        pass
    
    @abstractmethod
    async def stop_generation(self) -> None:
        """停止生成响应"""
        pass 