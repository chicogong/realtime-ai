"""WebSocket message models for validation using Pydantic"""

from typing import Dict, Literal, Optional, Type, Union

from pydantic import BaseModel


class WebSocketCommand(BaseModel):
    """Base model for WebSocket commands from client"""

    type: Literal["stop", "start", "reset", "interrupt", "text_input"]


class StopCommand(WebSocketCommand):
    """Stop command to halt all processing"""

    type: Literal["stop"] = "stop"


class StartCommand(WebSocketCommand):
    """Start command to begin ASR recognition"""

    type: Literal["start"] = "start"


class ResetCommand(WebSocketCommand):
    """Reset command to recreate ASR service"""

    type: Literal["reset"] = "reset"


class InterruptCommand(WebSocketCommand):
    """Interrupt command to stop current processing but keep connection"""

    type: Literal["interrupt"] = "interrupt"


class TextInputCommand(WebSocketCommand):
    """Text input command to send text directly to LLM (bypassing ASR)"""

    type: Literal["text_input"] = "text_input"
    text: str


# Type alias for all command types
AnyCommand = Union[StopCommand, StartCommand, ResetCommand, InterruptCommand, TextInputCommand]


class WebSocketResponse(BaseModel):
    """Base model for WebSocket responses to client"""

    type: str
    session_id: str


class ErrorResponse(WebSocketResponse):
    """Error response model"""

    type: Literal["error"] = "error"
    message: str


class TTSStartResponse(WebSocketResponse):
    """TTS start response model"""

    type: Literal["tts_start"] = "tts_start"
    format: str = "raw-16khz-16bit-mono-pcm"
    is_first: bool = False
    text: str


class TTSEndResponse(WebSocketResponse):
    """TTS end response model"""

    type: Literal["tts_end"] = "tts_end"


class StopAcknowledgedResponse(WebSocketResponse):
    """Stop acknowledged response model"""

    type: Literal["stop_acknowledged"] = "stop_acknowledged"
    message: str = "All processing stopped"
    queues_cleared: bool = True


class InterruptAcknowledgedResponse(WebSocketResponse):
    """Interrupt acknowledged response model"""

    type: Literal["interrupt_acknowledged"] = "interrupt_acknowledged"


class ASRResultResponse(WebSocketResponse):
    """ASR recognition result response model"""

    type: Literal["asr_result"] = "asr_result"
    text: str
    is_final: bool = False


class LLMStreamResponse(WebSocketResponse):
    """LLM streaming response model"""

    type: Literal["llm_stream"] = "llm_stream"
    content: str
    is_final: bool = False


def parse_command(data: Dict[str, object]) -> Optional[AnyCommand]:
    """Parse and validate a WebSocket command

    Args:
        data: Raw command data from client

    Returns:
        Validated command model or None if invalid
    """
    cmd_type = data.get("type")
    if not isinstance(cmd_type, str):
        return None

    command_models: Dict[str, Type[WebSocketCommand]] = {
        "stop": StopCommand,
        "start": StartCommand,
        "reset": ResetCommand,
        "interrupt": InterruptCommand,
        "text_input": TextInputCommand,
    }

    model_class = command_models.get(cmd_type)
    if model_class:
        try:
            return model_class(**data)  # type: ignore[arg-type, return-value]
        except Exception:
            return None
    return None
