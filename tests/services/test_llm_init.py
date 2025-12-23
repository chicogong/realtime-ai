"""Unit tests for services/llm/__init__.py"""

from unittest.mock import MagicMock, patch

import pytest


class TestCreateLLMService:
    """Tests for create_llm_service function"""

    @patch("services.llm.Config")
    def test_create_openai_missing_key(self, mock_config: MagicMock) -> None:
        """Test creating OpenAI LLM with missing key"""
        mock_config.LLM_PROVIDER = "openai"
        mock_config.OPENAI_API_KEY = None

        from services.llm import create_llm_service

        result = create_llm_service()
        assert result is None

    @patch("services.llm.Config")
    def test_create_unsupported_provider(self, mock_config: MagicMock) -> None:
        """Test creating LLM with unsupported provider"""
        mock_config.LLM_PROVIDER = "unsupported_provider"

        from services.llm import create_llm_service

        result = create_llm_service()
        assert result is None

    @patch("services.llm.OpenAIService")
    @patch("services.llm.Config")
    def test_create_openai_success(
        self, mock_config: MagicMock, mock_openai_service: MagicMock
    ) -> None:
        """Test successful OpenAI LLM creation"""
        mock_config.LLM_PROVIDER = "openai"
        mock_config.OPENAI_API_KEY = "test-api-key"
        mock_config.OPENAI_MODEL = "gpt-3.5-turbo"
        mock_config.OPENAI_BASE_URL = None

        mock_instance = MagicMock()
        mock_openai_service.return_value = mock_instance

        from services.llm import create_llm_service

        result = create_llm_service()
        assert result == mock_instance

    @patch("services.llm.OpenAIService")
    @patch("services.llm.Config")
    def test_create_llm_exception(
        self, mock_config: MagicMock, mock_openai_service: MagicMock
    ) -> None:
        """Test LLM creation with exception"""
        mock_config.LLM_PROVIDER = "openai"
        mock_config.OPENAI_API_KEY = "test-api-key"
        mock_config.OPENAI_MODEL = "gpt-3.5-turbo"
        mock_config.OPENAI_BASE_URL = None

        mock_openai_service.side_effect = Exception("Test error")

        from services.llm import create_llm_service

        result = create_llm_service()
        assert result is None
