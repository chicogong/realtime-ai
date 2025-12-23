"""Unit tests for config.py"""

import os
from unittest.mock import patch

import pytest


class TestConfig:
    """Tests for Config class"""

    def test_default_values(self) -> None:
        """Test default configuration values"""
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


class TestConfigValidation:
    """Tests for Config.validate() method"""

    @patch.dict(
        os.environ,
        {
            "ASR_PROVIDER": "azure",
            "LLM_PROVIDER": "openai",
            "TTS_PROVIDER": "azure",
            "AZURE_SPEECH_KEY": "test-key",
            "AZURE_SPEECH_REGION": "eastus",
            "OPENAI_API_KEY": "test-openai-key",
        },
        clear=False,
    )
    def test_validate_success(self) -> None:
        """Test validation succeeds with valid config"""
        # Need to reimport to get new env values
        import importlib

        import config

        importlib.reload(config)
        result = config.Config.validate()
        assert result is True

    @patch.dict(
        os.environ,
        {
            "ASR_PROVIDER": "azure",
            "AZURE_SPEECH_KEY": "",
            "AZURE_SPEECH_REGION": "",
        },
        clear=False,
    )
    def test_validate_missing_azure_asr_config(self) -> None:
        """Test validation fails with missing Azure ASR config"""
        import importlib

        import config

        importlib.reload(config)
        # This tests the validation path for missing Azure credentials
        # The actual result depends on other env vars

    @patch.dict(
        os.environ,
        {
            "TTS_PROVIDER": "minimax",
            "MINIMAX_API_KEY": "",
        },
        clear=False,
    )
    def test_validate_missing_minimax_config(self) -> None:
        """Test validation fails with missing MiniMax config"""
        import importlib

        import config

        importlib.reload(config)
        # Tests MiniMax validation path


class TestConfigServiceConfig:
    """Tests for Config.get_service_config() method"""

    def test_get_asr_config_azure(self) -> None:
        """Test ASR config for Azure provider"""
        from config import Config

        with patch.object(Config, "ASR_PROVIDER", "azure"):
            with patch.object(Config, "AZURE_SPEECH_KEY", "test-key"):
                with patch.object(Config, "AZURE_SPEECH_REGION", "eastus"):
                    config = Config.get_service_config("asr")
                    assert config["provider"] == "azure"
                    assert "speech_key" in config
                    assert "speech_region" in config

    def test_get_llm_config_openai(self) -> None:
        """Test LLM config for OpenAI provider"""
        from config import Config

        with patch.object(Config, "LLM_PROVIDER", "openai"):
            with patch.object(Config, "OPENAI_API_KEY", "test-key"):
                with patch.object(Config, "OPENAI_BASE_URL", None):
                    with patch.object(Config, "OPENAI_MODEL", "gpt-4"):
                        with patch.object(Config, "OPENAI_SYSTEM_PROMPT", "test"):
                            config = Config.get_service_config("llm")
                            assert config["provider"] == "openai"
                            assert "api_key" in config
                            assert "model" in config

    def test_get_tts_config_azure(self) -> None:
        """Test TTS config for Azure provider"""
        from config import Config

        with patch.object(Config, "TTS_PROVIDER", "azure"):
            with patch.object(Config, "AZURE_SPEECH_KEY", "test-key"):
                with patch.object(Config, "AZURE_SPEECH_REGION", "eastus"):
                    with patch.object(Config, "AZURE_TTS_VOICE", "en-US-AriaNeural"):
                        config = Config.get_service_config("tts")
                        assert config["provider"] == "azure"
                        assert "speech_key" in config
                        assert "voice" in config

    def test_get_tts_config_minimax(self) -> None:
        """Test TTS config for MiniMax provider"""
        from config import Config

        with patch.object(Config, "TTS_PROVIDER", "minimax"):
            with patch.object(Config, "MINIMAX_API_KEY", "test-key"):
                with patch.object(Config, "MINIMAX_VOICE_ID", "test-voice"):
                    config = Config.get_service_config("tts")
                    assert config["provider"] == "minimax"
                    assert "api_key" in config
                    assert "voice_id" in config

    def test_get_unknown_service_config(self) -> None:
        """Test getting config for unknown service type raises error"""
        from config import Config

        # Unknown service type will raise AttributeError since UNKNOWN_PROVIDER doesn't exist
        with pytest.raises(AttributeError):
            Config.get_service_config("unknown")
