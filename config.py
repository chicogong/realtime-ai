import os
from dotenv import load_dotenv
from loguru import logger

# 加载环境变量
load_dotenv()

class Config:
    """集中管理应用配置"""
    # 服务提供商选择
    ASR_PROVIDER = os.getenv("ASR_PROVIDER", "azure")  # 支持: azure, (未来其他提供商)
    LLM_PROVIDER = os.getenv("LLM_PROVIDER", "openai")  # 支持: openai, (未来其他提供商)
    TTS_PROVIDER = os.getenv("TTS_PROVIDER", "azure")  # 支持: azure, minimax, (未来其他提供商)
    
    # Azure 语音服务配置
    AZURE_SPEECH_KEY = os.getenv("AZURE_SPEECH_KEY")
    AZURE_SPEECH_REGION = os.getenv("AZURE_SPEECH_REGION")
    AZURE_TTS_VOICE = os.getenv("AZURE_TTS_VOICE", "zh-CN-XiaoxiaoNeural")
    
    # MiniMax TTS配置
    MINIMAX_API_KEY = os.getenv("MINIMAX_API_KEY")
    MINIMAX_VOICE_ID = os.getenv("MINIMAX_VOICE_ID", "male-qn-qingse")  # 默认使用青涩音色
    
    # OpenAI API配置
    OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
    OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL")
    OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-3.5-turbo")
    OPENAI_SYSTEM_PROMPT = os.getenv("OPENAI_SYSTEM_PROMPT", 
                                    "你是一个智能语音助手小蕊，请用口语化、简短的回答客户问题，不要回复任何表情符号")
    
    # 语音识别配置
    ASR_LANGUAGE = os.getenv("ASR_LANGUAGE", "zh-CN")
    VOICE_ENERGY_THRESHOLD = float(os.getenv("VOICE_ENERGY_THRESHOLD", "0.05"))  # 语音能量阈值

    # WebSocket配置
    WEBSOCKET_PING_INTERVAL = int(os.getenv("WEBSOCKET_PING_INTERVAL", "30"))  # WebSocket心跳间隔（秒）
    
    # 会话配置
    SESSION_TIMEOUT = int(os.getenv("SESSION_TIMEOUT", "600"))  # 会话超时时间（秒）
    
    # 调试配置
    DEBUG = os.getenv("DEBUG", "false").lower() == "true"  # 默认关闭调试模式
    
    @classmethod
    def validate(cls):
        """验证必要的配置是否存在"""
        # 验证ASR配置
        if cls.ASR_PROVIDER == "azure":
            if not cls.AZURE_SPEECH_KEY or not cls.AZURE_SPEECH_REGION:
                logger.error("Azure Speech凭据缺失，需设置AZURE_SPEECH_KEY和AZURE_SPEECH_REGION")
                return False
        
        # 验证LLM配置
        if cls.LLM_PROVIDER == "openai":
            if not cls.OPENAI_API_KEY:
                logger.error("OpenAI API密钥缺失，需设置OPENAI_API_KEY")
                return False
            
            logger.info(f"OpenAI模型: {cls.OPENAI_MODEL}" + (f", 自定义API: {cls.OPENAI_BASE_URL}" if cls.OPENAI_BASE_URL else ""))
        
        # 验证TTS配置
        if cls.TTS_PROVIDER == "azure":
            if not cls.AZURE_SPEECH_KEY or not cls.AZURE_SPEECH_REGION:
                logger.error("Azure Speech凭据缺失，需设置AZURE_SPEECH_KEY和AZURE_SPEECH_REGION")
                return False
        elif cls.TTS_PROVIDER == "minimax":
            if not cls.MINIMAX_API_KEY:
                logger.error("MiniMax API密钥缺失，需设置MINIMAX_API_KEY")
                return False
            logger.info(f"MiniMax TTS语音ID: {cls.MINIMAX_VOICE_ID}")
        
        logger.info("配置验证通过")
        return True

# 验证配置
if not Config.validate():
    logger.warning("配置验证失败，某些功能可能无法正常工作") 