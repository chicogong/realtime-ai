"""Unit tests for services/asr/__init__.py"""

from unittest.mock import MagicMock, patch


class TestCreateASRService:
    """Tests for create_asr_service function"""

    @patch("services.asr.Config")
    def test_create_azure_asr_missing_key(self, mock_config: MagicMock) -> None:
        """Test creating Azure ASR with missing key"""
        mock_config.ASR_PROVIDER = "azure"
        mock_config.AZURE_SPEECH_KEY = None
        mock_config.AZURE_SPEECH_REGION = "eastus"

        from services.asr import create_asr_service

        result = create_asr_service()
        assert result is None

    @patch("services.asr.Config")
    def test_create_azure_asr_missing_region(self, mock_config: MagicMock) -> None:
        """Test creating Azure ASR with missing region"""
        mock_config.ASR_PROVIDER = "azure"
        mock_config.AZURE_SPEECH_KEY = "test-key"
        mock_config.AZURE_SPEECH_REGION = None

        from services.asr import create_asr_service

        result = create_asr_service()
        assert result is None

    @patch("services.asr.Config")
    def test_create_unsupported_provider(self, mock_config: MagicMock) -> None:
        """Test creating ASR with unsupported provider"""
        mock_config.ASR_PROVIDER = "unsupported_provider"

        from services.asr import create_asr_service

        result = create_asr_service()
        assert result is None

    @patch("services.asr.AzureASRService")
    @patch("services.asr.Config")
    def test_create_azure_asr_success(self, mock_config: MagicMock, mock_azure_service: MagicMock) -> None:
        """Test successful Azure ASR creation"""
        mock_config.ASR_PROVIDER = "azure"
        mock_config.AZURE_SPEECH_KEY = "test-key"
        mock_config.AZURE_SPEECH_REGION = "eastus"
        mock_config.ASR_LANGUAGE = "en-US"

        mock_instance = MagicMock()
        mock_azure_service.return_value = mock_instance

        from services.asr import create_asr_service

        result = create_asr_service()
        assert result == mock_instance

    @patch("services.asr.AzureASRService")
    @patch("services.asr.Config")
    def test_create_asr_exception(self, mock_config: MagicMock, mock_azure_service: MagicMock) -> None:
        """Test ASR creation with exception"""
        mock_config.ASR_PROVIDER = "azure"
        mock_config.AZURE_SPEECH_KEY = "test-key"
        mock_config.AZURE_SPEECH_REGION = "eastus"
        mock_config.ASR_LANGUAGE = "en-US"

        mock_azure_service.side_effect = Exception("Test error")

        from services.asr import create_asr_service

        result = create_asr_service()
        assert result is None
