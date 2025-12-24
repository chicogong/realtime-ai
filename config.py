import os
from typing import Any, Dict

from dotenv import load_dotenv
from loguru import logger

from utils.security import mask_sensitive

# Load environment variables
load_dotenv()


class Config:
    """Application configuration settings"""

    # Service provider selection
    ASR_PROVIDER = os.getenv("ASR_PROVIDER", "azure")
    LLM_PROVIDER = os.getenv("LLM_PROVIDER", "openai")
    TTS_PROVIDER = os.getenv("TTS_PROVIDER", "azure")

    # ASR settings
    ASR_LANGUAGE = os.getenv("ASR_LANGUAGE", "en-US")
    VOICE_ENERGY_THRESHOLD = float(os.getenv("VOICE_ENERGY_THRESHOLD", "0.05"))

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

    # WebSocket settings
    WEBSOCKET_PING_INTERVAL = int(os.getenv("WEBSOCKET_PING_INTERVAL", "30"))

    # Session settings
    SESSION_TIMEOUT = int(os.getenv("SESSION_TIMEOUT", "600"))

    # Debug settings
    DEBUG = os.getenv("DEBUG", "false").lower() == "true"

    @classmethod
    def _validate_provider_config(cls) -> Dict[str, bool]:
        """Validate provider-specific configurations"""
        validation_results: Dict[str, bool] = {}

        # Azure Speech validation (ASR/TTS)
        azure_credentials_valid = bool(cls.AZURE_SPEECH_KEY and cls.AZURE_SPEECH_REGION)
        validation_results["azure"] = azure_credentials_valid

        # OpenAI validation
        openai_valid = bool(cls.OPENAI_API_KEY)
        validation_results["openai"] = openai_valid

        # MiniMax validation
        minimax_valid = bool(cls.MINIMAX_API_KEY)
        validation_results["minimax"] = minimax_valid

        return validation_results

    @classmethod
    def validate(cls) -> bool:
        """Validate required configuration"""
        validation_errors = []
        provider_validations = cls._validate_provider_config()

        # Check ASR provider configuration
        if cls.ASR_PROVIDER == "azure" and not provider_validations["azure"]:
            validation_errors.append(
                "Azure Speech credentials missing: AZURE_SPEECH_KEY and AZURE_SPEECH_REGION required for ASR"
            )

        # Check LLM provider configuration
        if cls.LLM_PROVIDER == "openai" and not provider_validations["openai"]:
            validation_errors.append("OpenAI API key missing: OPENAI_API_KEY required for LLM")

        # Check TTS provider configuration
        if cls.TTS_PROVIDER == "azure" and not provider_validations["azure"]:
            validation_errors.append(
                "Azure Speech credentials missing: AZURE_SPEECH_KEY and AZURE_SPEECH_REGION required for TTS"
            )
        elif cls.TTS_PROVIDER == "minimax" and not provider_validations["minimax"]:
            validation_errors.append("MiniMax API key missing: MINIMAX_API_KEY required for TTS")

        # Report validation errors
        if validation_errors:
            for error in validation_errors:
                logger.error(error)
            return False

        logger.info("Configuration validated successfully")
        return True

    @classmethod
    def get_service_config(cls, service_type: str) -> Dict[str, Any]:
        """Get provider-specific configuration for a service type"""
        config = {"provider": getattr(cls, f"{service_type.upper()}_PROVIDER")}

        if service_type.upper() == "ASR":
            config.update(
                {
                    "language": cls.ASR_LANGUAGE,
                    "energy_threshold": cls.VOICE_ENERGY_THRESHOLD,
                }
            )

            if config["provider"] == "azure":
                config.update(
                    {
                        "speech_key": cls.AZURE_SPEECH_KEY,
                        "speech_region": cls.AZURE_SPEECH_REGION,
                    }
                )

        elif service_type.upper() == "LLM":
            if config["provider"] == "openai":
                config.update(
                    {
                        "api_key": cls.OPENAI_API_KEY,
                        "base_url": cls.OPENAI_BASE_URL,
                        "model": cls.OPENAI_MODEL,
                        "system_prompt": cls.OPENAI_SYSTEM_PROMPT,
                    }
                )

        elif service_type.upper() == "TTS":
            if config["provider"] == "azure":
                config.update(
                    {
                        "speech_key": cls.AZURE_SPEECH_KEY,
                        "speech_region": cls.AZURE_SPEECH_REGION,
                        "voice": cls.AZURE_TTS_VOICE,
                    }
                )
            elif config["provider"] == "minimax":
                config.update(
                    {
                        "api_key": cls.MINIMAX_API_KEY,
                        "voice_id": cls.MINIMAX_VOICE_ID,
                    }
                )

        return config

    @classmethod
    def get_service_config_masked(cls, service_type: str) -> Dict[str, str]:
        """Get provider-specific configuration with sensitive data masked (for logging)"""
        config = cls.get_service_config(service_type)
        return mask_sensitive(config)


# Validate configuration
Config.validate()
