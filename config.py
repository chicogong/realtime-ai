import os

from dotenv import load_dotenv
from loguru import logger

# Load environment variables
load_dotenv()


class Config:
    """Application configuration settings"""

    # Service provider selection
    ASR_PROVIDER = os.getenv("ASR_PROVIDER", "azure")
    LLM_PROVIDER = os.getenv("LLM_PROVIDER", "openai")
    TTS_PROVIDER = os.getenv("TTS_PROVIDER", "azure")

    # Azure Speech service
    AZURE_SPEECH_KEY = os.getenv("AZURE_SPEECH_KEY")
    AZURE_SPEECH_REGION = os.getenv("AZURE_SPEECH_REGION")
    AZURE_TTS_VOICE = os.getenv("AZURE_TTS_VOICE", "en-US-AriaNeural")

    # MiniMax TTS
    MINIMAX_API_KEY = os.getenv("MINIMAX_API_KEY")
    MINIMAX_VOICE_ID = os.getenv("MINIMAX_VOICE_ID", "male-qn-qingse")

    # OpenAI API
    OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
    OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL")
    OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-3.5-turbo")
    OPENAI_SYSTEM_PROMPT = os.getenv(
        "OPENAI_SYSTEM_PROMPT",
        "You are an intelligent voice assistant. Please provide concise, conversational answers.",
    )

    # Speech recognition
    ASR_LANGUAGE = os.getenv("ASR_LANGUAGE", "en-US")
    VOICE_ENERGY_THRESHOLD = float(os.getenv("VOICE_ENERGY_THRESHOLD", "0.05"))

    # WebSocket
    WEBSOCKET_PING_INTERVAL = int(os.getenv("WEBSOCKET_PING_INTERVAL", "30"))

    # Session
    SESSION_TIMEOUT = int(os.getenv("SESSION_TIMEOUT", "600"))

    # Debug
    DEBUG = os.getenv("DEBUG", "false").lower() == "true"

    @classmethod
    def validate(cls) -> bool:
        """Validate required configuration"""
        # Validate ASR config
        if cls.ASR_PROVIDER == "azure" and (not cls.AZURE_SPEECH_KEY or not cls.AZURE_SPEECH_REGION):
            logger.error("Azure Speech credentials missing: AZURE_SPEECH_KEY and AZURE_SPEECH_REGION required")
            return False

        # Validate LLM config
        if cls.LLM_PROVIDER == "openai" and not cls.OPENAI_API_KEY:
            logger.error("OpenAI API key missing: OPENAI_API_KEY required")
            return False

        # Validate TTS config
        if cls.TTS_PROVIDER == "azure" and (not cls.AZURE_SPEECH_KEY or not cls.AZURE_SPEECH_REGION):
            logger.error("Azure Speech credentials missing: AZURE_SPEECH_KEY and AZURE_SPEECH_REGION required")
            return False

        if cls.TTS_PROVIDER == "minimax" and not cls.MINIMAX_API_KEY:
            logger.error("MiniMax API key missing: MINIMAX_API_KEY required")
            return False

        logger.info("Configuration validated")
        return True


# Validate configuration
if not Config.validate():
    logger.warning("Configuration validation failed, some features may not work properly")
