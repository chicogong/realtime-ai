from typing import Optional
from loguru import logger

from config import Config
from services.llm.base import BaseLLMService
from services.llm.openai_llm import OpenAIService

def create_llm_service() -> Optional[BaseLLMService]:
    """创建LLM服务实例
    
    Returns:
        LLM服务实例，如果创建失败则返回None
    """
    try:
        if Config.LLM_PROVIDER == "openai":
            logger.info("创建OpenAI LLM服务")
            return OpenAIService(
                api_key=Config.OPENAI_API_KEY,
                model=Config.OPENAI_MODEL,
                base_url=Config.OPENAI_BASE_URL
            )
        # 未来可以在这里添加其他LLM提供商的支持
        # elif Config.LLM_PROVIDER == "other_provider":
        #     return OtherLLMService(...)
        else:
            logger.error(f"不支持的LLM提供商: {Config.LLM_PROVIDER}")
            return None
    except Exception as e:
        logger.error(f"LLM服务创建失败: {e}")
        return None
