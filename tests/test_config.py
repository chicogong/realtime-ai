"""Unit tests for config.py"""

import os

import pytest


class TestConfig:
    """Tests for Config class"""

    def test_default_values(self) -> None:
        """Test default configuration values"""
        # Import after environment might be set
        from config import Config

        # These should have defaults
        assert Config.ASR_LANGUAGE == os.getenv("ASR_LANGUAGE", "en-US")
        assert Config.OPENAI_MODEL == os.getenv("OPENAI_MODEL", "gpt-3.5-turbo")

    def test_get_service_config_asr(self) -> None:
        """Test getting ASR service config"""
        from config import Config

        config = Config.get_service_config("asr")
        assert "provider" in config
        assert "language" in config
        assert "energy_threshold" in config

    def test_get_service_config_llm(self) -> None:
        """Test getting LLM service config"""
        from config import Config

        config = Config.get_service_config("llm")
        assert "provider" in config

    def test_get_service_config_tts(self) -> None:
        """Test getting TTS service config"""
        from config import Config

        config = Config.get_service_config("tts")
        assert "provider" in config

    def test_get_service_config_case_insensitive(self) -> None:
        """Test service config is case insensitive"""
        from config import Config

        config_upper = Config.get_service_config("ASR")
        config_lower = Config.get_service_config("asr")
        assert config_upper["provider"] == config_lower["provider"]

    def test_validate_provider_config_returns_dict(self) -> None:
        """Test provider configuration validation returns dict"""
        from config import Config

        result = Config._validate_provider_config()
        assert isinstance(result, dict)
        assert "azure" in result
        assert "openai" in result
        assert "minimax" in result

    def test_voice_energy_threshold_is_float(self) -> None:
        """Test VOICE_ENERGY_THRESHOLD is a float"""
        from config import Config

        assert isinstance(Config.VOICE_ENERGY_THRESHOLD, float)

    def test_session_timeout_is_int(self) -> None:
        """Test SESSION_TIMEOUT is an integer"""
        from config import Config

        assert isinstance(Config.SESSION_TIMEOUT, int)

    def test_websocket_ping_interval_is_int(self) -> None:
        """Test WEBSOCKET_PING_INTERVAL is an integer"""
        from config import Config

        assert isinstance(Config.WEBSOCKET_PING_INTERVAL, int)
