"""Unit tests for services/tts/__init__.py"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestCreateTTSService:
    """Tests for create_tts_service function"""

    @patch("services.tts.Config")
    def test_create_azure_tts_missing_key(self, mock_config: MagicMock) -> None:
        """Test creating Azure TTS with missing key"""
        mock_config.TTS_PROVIDER = "azure"
        mock_config.AZURE_SPEECH_KEY = None
        mock_config.AZURE_SPEECH_REGION = "eastus"

        from services.tts import create_tts_service

        result = create_tts_service()
        assert result is None

    @patch("services.tts.Config")
    def test_create_azure_tts_missing_region(self, mock_config: MagicMock) -> None:
        """Test creating Azure TTS with missing region"""
        mock_config.TTS_PROVIDER = "azure"
        mock_config.AZURE_SPEECH_KEY = "test-key"
        mock_config.AZURE_SPEECH_REGION = None

        from services.tts import create_tts_service

        result = create_tts_service()
        assert result is None

    @patch("services.tts.Config")
    def test_create_minimax_tts_missing_key(self, mock_config: MagicMock) -> None:
        """Test creating MiniMax TTS with missing key"""
        mock_config.TTS_PROVIDER = "minimax"
        mock_config.MINIMAX_API_KEY = None

        from services.tts import create_tts_service

        result = create_tts_service()
        assert result is None

    @patch("services.tts.Config")
    def test_create_unsupported_provider(self, mock_config: MagicMock) -> None:
        """Test creating TTS with unsupported provider"""
        mock_config.TTS_PROVIDER = "unsupported_provider"

        from services.tts import create_tts_service

        result = create_tts_service()
        assert result is None

    @patch("services.tts.AzureTTSService")
    @patch("services.tts.Config")
    def test_create_azure_tts_success(
        self, mock_config: MagicMock, mock_azure_service: MagicMock
    ) -> None:
        """Test successful Azure TTS creation"""
        mock_config.TTS_PROVIDER = "azure"
        mock_config.AZURE_SPEECH_KEY = "test-key"
        mock_config.AZURE_SPEECH_REGION = "eastus"
        mock_config.AZURE_TTS_VOICE = "en-US-AriaNeural"

        mock_instance = MagicMock()
        mock_azure_service.return_value = mock_instance

        from services.tts import create_tts_service

        result = create_tts_service()
        assert result == mock_instance

    @patch("services.tts.MiniMaxTTSService")
    @patch("services.tts.Config")
    def test_create_minimax_tts_success(
        self, mock_config: MagicMock, mock_minimax_service: MagicMock
    ) -> None:
        """Test successful MiniMax TTS creation"""
        mock_config.TTS_PROVIDER = "minimax"
        mock_config.MINIMAX_API_KEY = "test-api-key"
        mock_config.MINIMAX_VOICE_ID = "male-qn-qingse"

        mock_instance = MagicMock()
        mock_minimax_service.return_value = mock_instance

        from services.tts import create_tts_service

        result = create_tts_service()
        assert result == mock_instance

    @patch("services.tts.AzureTTSService")
    @patch("services.tts.Config")
    def test_create_tts_with_session_id(
        self, mock_config: MagicMock, mock_azure_service: MagicMock
    ) -> None:
        """Test TTS creation with session ID"""
        mock_config.TTS_PROVIDER = "azure"
        mock_config.AZURE_SPEECH_KEY = "test-key"
        mock_config.AZURE_SPEECH_REGION = "eastus"
        mock_config.AZURE_TTS_VOICE = "en-US-AriaNeural"

        mock_instance = MagicMock()
        mock_azure_service.return_value = mock_instance

        from services.tts import create_tts_service

        result = create_tts_service(session_id="test-session-123")
        assert result == mock_instance
        mock_instance.set_session_id.assert_called_once_with("test-session-123")

    @patch("services.tts.AzureTTSService")
    @patch("services.tts.Config")
    def test_create_tts_exception(
        self, mock_config: MagicMock, mock_azure_service: MagicMock
    ) -> None:
        """Test TTS creation with exception"""
        mock_config.TTS_PROVIDER = "azure"
        mock_config.AZURE_SPEECH_KEY = "test-key"
        mock_config.AZURE_SPEECH_REGION = "eastus"
        mock_config.AZURE_TTS_VOICE = "en-US-AriaNeural"

        mock_azure_service.side_effect = Exception("Test error")

        from services.tts import create_tts_service

        result = create_tts_service()
        assert result is None


class TestCloseAllTTSServices:
    """Tests for close_all_tts_services function"""

    @pytest.mark.asyncio
    async def test_close_all_azure(self) -> None:
        """Test closing all Azure TTS services"""
        with patch("services.tts.Config") as mock_config, \
             patch("services.tts.AzureTTSService") as mock_azure_service:
            mock_config.TTS_PROVIDER = "azure"
            mock_azure_service.close_all = AsyncMock()

            from services.tts import close_all_tts_services

            await close_all_tts_services()

    @pytest.mark.asyncio
    async def test_close_all_minimax(self) -> None:
        """Test closing all MiniMax TTS services"""
        with patch("services.tts.Config") as mock_config, \
             patch("services.tts.MiniMaxTTSService") as mock_minimax_service:
            mock_config.TTS_PROVIDER = "minimax"
            mock_minimax_service.close_all = AsyncMock()

            from services.tts import close_all_tts_services

            await close_all_tts_services()
