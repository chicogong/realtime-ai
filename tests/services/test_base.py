"""Unit tests for base service classes"""

import pytest

from services.asr.base import BaseASRService
from services.llm.base import BaseLLMService
from services.tts.base import BaseTTSService


class TestBaseASRService:
    """Tests for BaseASRService abstract class"""

    def test_is_abstract_class(self) -> None:
        """Test that BaseASRService cannot be instantiated directly"""
        with pytest.raises(TypeError):
            BaseASRService()  # type: ignore

    def test_has_required_methods(self) -> None:
        """Test that BaseASRService defines required abstract methods"""
        assert hasattr(BaseASRService, "start_recognition")
        assert hasattr(BaseASRService, "stop_recognition")


class TestBaseLLMService:
    """Tests for BaseLLMService abstract class"""

    def test_is_abstract_class(self) -> None:
        """Test that BaseLLMService cannot be instantiated directly"""
        with pytest.raises(TypeError):
            BaseLLMService()  # type: ignore

    def test_has_required_methods(self) -> None:
        """Test that BaseLLMService defines required abstract methods"""
        assert hasattr(BaseLLMService, "generate_response")


class TestBaseTTSService:
    """Tests for BaseTTSService abstract class"""

    def test_is_abstract_class(self) -> None:
        """Test that BaseTTSService cannot be instantiated directly"""
        with pytest.raises(TypeError):
            BaseTTSService()  # type: ignore

    def test_has_required_methods(self) -> None:
        """Test that BaseTTSService defines required abstract methods"""
        assert hasattr(BaseTTSService, "synthesize_text")
        assert hasattr(BaseTTSService, "close")
