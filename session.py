import time
import uuid
import asyncio
from typing import Dict, Optional, List, Any

from loguru import logger


class SessionState:
    """Manages user session state"""

    def __init__(self, session_id: Optional[str] = None) -> None:
        self.session_id = session_id or str(uuid.uuid4())
        self.is_processing_llm = False
        self.is_tts_active = False
        self.response_stream: Any = None
        self.interrupt_requested = False
        self.tts_processor: Any = None
        self.last_activity = time.time()
        self.asr_recognizer: Any = None
        
        # Pipeline components
        self.asr_queue: asyncio.Queue[str] = asyncio.Queue()  # Queue for ASR results
        self.llm_queue: asyncio.Queue[str] = asyncio.Queue()  # Queue for LLM responses
        self.tts_queue: asyncio.Queue[str] = asyncio.Queue()  # Queue for TTS tasks
        
        # Pipeline tasks
        self.pipeline_tasks: List[asyncio.Task] = []
        self.current_llm_task: Optional[asyncio.Task] = None
        self.current_tts_task: Optional[asyncio.Task] = None

    def request_interrupt(self) -> None:
        logger.info(f"Interrupt requested: {self.session_id}")
        self.interrupt_requested = True
        self._cancel_pipeline_tasks()

    def clear_interrupt(self) -> None:
        self.interrupt_requested = False

    def is_interrupted(self) -> bool:
        return self.interrupt_requested

    def update_activity(self) -> None:
        self.last_activity = time.time()

    def is_inactive(self, timeout_seconds: int = 300) -> bool:
        return (time.time() - self.last_activity) > timeout_seconds
        
    def _cancel_pipeline_tasks(self) -> None:
        """Cancel all pipeline tasks"""
        for task in self.pipeline_tasks:
            if not task.done():
                task.cancel()
        self.pipeline_tasks.clear()
        
        if self.current_llm_task and not self.current_llm_task.done():
            self.current_llm_task.cancel()
            self.current_llm_task = None
            
        if self.current_tts_task and not self.current_tts_task.done():
            self.current_tts_task.cancel()
            self.current_tts_task = None
            
        # Clear all queues
        for queue in [self.asr_queue, self.llm_queue, self.tts_queue]:
            while not queue.empty():
                try:
                    queue.get_nowait()
                except asyncio.QueueEmpty:
                    break


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