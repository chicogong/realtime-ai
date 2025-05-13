import logging
import asyncio
from typing import AsyncGenerator, Dict, Any, List, Optional

import async_timeout
from openai import AsyncOpenAI

from config import Config
from services.llm.base import BaseLLMService

logger = logging.getLogger(__name__)

class OpenAIService(BaseLLMService):
    """OpenAI语言模型服务实现"""
    
    def __init__(self, api_key: str, model: str, base_url: Optional[str] = None):
        """初始化OpenAI服务
        
        Args:
            api_key: OpenAI API密钥
            model: 模型名称，如"gpt-3.5-turbo"
            base_url: 可选的API基础URL，用于自定义端点
        """
        super().__init__()
        self.api_key = api_key
        self.model = model
        self.base_url = base_url
        self.client = AsyncOpenAI(
            api_key=api_key,
            base_url=base_url if base_url else None
        )
        self.active_generation = None
        self.stop_requested = False
        
        logger.info(f"OpenAI服务初始化: 模型={model}")
        if base_url:
            logger.info(f"使用自定义API端点: {base_url}")
    
    async def generate_response(self, text: str, system_prompt: Optional[str] = None) -> AsyncGenerator[str, None]:
        """生成文本响应
        
        Args:
            text: 用户输入文本
            system_prompt: 系统提示，用于设置AI助手的行为
            
        Returns:
            异步生成器，产生文本片段
        """
        self.stop_requested = False
        
        if not system_prompt:
            system_prompt = Config.OPENAI_SYSTEM_PROMPT
        
        try:
            async with async_timeout.timeout(30):  # 30秒超时
                # 创建流式回复
                response_stream = await self.client.chat.completions.create(
                    model=self.model,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": text}
                    ],
                    stream=True
                )
                
                self.active_generation = response_stream
                
                # 迭代流式回复
                async for chunk in response_stream:
                    # 检查是否请求了停止
                    if self.stop_requested:
                        logger.info("检测到停止请求，终止LLM生成")
                        break
                        
                    if hasattr(chunk.choices[0], "delta"):
                        delta = chunk.choices[0].delta
                        if hasattr(delta, "content") and delta.content:
                            yield delta.content
                
                # 生成完成或被中断
                self.active_generation = None
        
        except asyncio.TimeoutError:
            logger.error("LLM响应生成超时（30秒）")
            raise
        except Exception as e:
            logger.error(f"LLM响应生成错误: {e}")
            raise
    
    async def stop_generation(self) -> None:
        """停止生成响应"""
        logger.info("请求停止LLM生成")
        self.stop_requested = True
        
        # 这里我们只是设置标志位，实际的停止操作在generate_response中检查标志位实现 