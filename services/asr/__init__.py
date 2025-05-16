from typing import Optional

from loguru import logger

from config import Config
from services.asr.azure_asr import AzureASRService
from services.asr.base import BaseASRService


def create_asr_service() -> Optional[BaseASRService]:
    """创建ASR服务实例

    Returns:
        ASR服务实例，如果创建失败则返回None
    """
    try:
        if Config.ASR_PROVIDER == "azure":
            logger.info("创建Azure ASR服务")
            return AzureASRService(
                subscription_key=Config.AZURE_SPEECH_KEY,
                region=Config.AZURE_SPEECH_REGION,
                language=Config.ASR_LANGUAGE,
            )
        # 未来可以在这里添加其他ASR提供商的支持
        # elif Config.ASR_PROVIDER == "other_provider":
        #     return OtherASRService(...)
        else:
            logger.error(f"不支持的ASR提供商: {Config.ASR_PROVIDER}")
            return None
    except Exception as e:
        logger.error(f"ASR服务创建失败: {e}")
        return None
