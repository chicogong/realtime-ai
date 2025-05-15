import logging
from abc import ABC, abstractmethod
from typing import AsyncGenerator, Optional

logger = logging.getLogger(__name__)

class BaseLLMService(ABC):
    """Abstract base class for LLM services"""
    
    @abstractmethod
    async def generate_response(self, text: str, system_prompt: Optional[str] = None) -> AsyncGenerator[str, None]:
        """Generate text response
        
        Args:
            text: User input text
            system_prompt: System prompt for AI assistant behavior
            
        Returns:
            Async generator yielding text chunks
        """
        pass
    
    @abstractmethod
    async def stop_generation(self) -> None:
        """Stop response generation"""
        pass 