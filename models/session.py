import time
import uuid
from typing import Dict

from loguru import logger


class SessionState:
    """Manages user session state"""

    def __init__(self, session_id: str = None):
        self.session_id = session_id or str(uuid.uuid4())
        self.is_processing_llm = False
        self.is_tts_active = False
        self.response_stream = None
        self.interrupt_requested = False
        self.tts_processor = None
        self.last_activity = time.time()
        self.asr_recognizer = None

    def request_interrupt(self) -> None:
        logger.info(f"Interrupt requested: {self.session_id}")
        self.interrupt_requested = True

    def clear_interrupt(self) -> None:
        self.interrupt_requested = False

    def is_interrupted(self) -> bool:
        return self.interrupt_requested

    def update_activity(self) -> None:
        self.last_activity = time.time()

    def is_inactive(self, timeout_seconds: int = 300) -> bool:
        return (time.time() - self.last_activity) > timeout_seconds


# Global session state dictionary
sessions: Dict[str, SessionState] = {}


def get_session(session_id: str) -> SessionState:
    """Get or create session state"""
    if session_id not in sessions:
        sessions[session_id] = SessionState(session_id)
    return sessions[session_id]


def remove_session(session_id: str) -> None:
    """Remove a session"""
    if session_id in sessions:
        del sessions[session_id]
        logger.info(f"Session removed: {session_id}")


def get_all_sessions() -> Dict[str, SessionState]:
    """Get all active sessions"""
    return sessions
