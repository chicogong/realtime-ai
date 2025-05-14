from typing import Optional
from loguru import logger

from config import Config
from services.tts.base import BaseTTSService
from services.tts.azure_tts import AzureTTSService
from services.tts.minimax_tts import MiniMaxTTSService

def create_tts_service(session_id: Optional[str] = None) -> Optional[BaseTTSService]:
    """创建TTS服务实例
    
    Args:
        session_id: 可选的会话ID
        
    Returns:
        TTS服务实例，如果创建失败则返回None
    """
    try:
        tts_service = None
        
        if Config.TTS_PROVIDER == "azure":
            logger.info("创建Azure TTS服务")
            tts_service = AzureTTSService(
                subscription_key=Config.AZURE_SPEECH_KEY,
                region=Config.AZURE_SPEECH_REGION,
                voice_name=Config.AZURE_TTS_VOICE
            )
        elif Config.TTS_PROVIDER == "minimax":
            logger.info("创建MiniMax TTS服务")
            tts_service = MiniMaxTTSService(
                api_key=Config.MINIMAX_API_KEY,
                voice_id=Config.MINIMAX_VOICE_ID
            )
        # 未来可以在这里添加其他TTS提供商的支持
        # elif Config.TTS_PROVIDER == "other_provider":
        #     tts_service = OtherTTSService(...)
        else:
            logger.error(f"不支持的TTS提供商: {Config.TTS_PROVIDER}")
            return None
        
        # 设置会话ID
        if tts_service and session_id:
            tts_service.set_session_id(session_id)
            
        return tts_service
    except Exception as e:
        logger.error(f"TTS服务创建失败: {e}")
        return None

async def close_all_tts_services() -> None:
    """关闭所有TTS服务资源"""
    if Config.TTS_PROVIDER == "azure":
        await AzureTTSService.close_all()
    elif Config.TTS_PROVIDER == "minimax":
        await MiniMaxTTSService.close_all()
    # 未来可以在这里添加其他TTS提供商的清理代码
