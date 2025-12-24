import asyncio
import time
import uuid
from threading import RLock
from typing import Any, Dict, List, Optional

from loguru import logger

from config import Config

# Thread-safe lock for session dictionary
_sessions_lock = RLock()


class SessionState:
    """Manages user session state and pipeline resources"""

    def __init__(self, session_id: Optional[str] = None) -> None:
        self.session_id = session_id or str(uuid.uuid4())
        self.last_activity = time.time()

        # State flags
        self.is_processing_llm = False
        self.is_tts_active = False
        self.interrupt_requested = False

        # Service components
        self.response_stream: Any = None
        self.tts_processor: Any = None
        self.asr_recognizer: Any = None

        # Pipeline components
        self.asr_queue: asyncio.Queue[str] = asyncio.Queue()
        self.llm_queue: asyncio.Queue[str] = asyncio.Queue()
        self.tts_queue: asyncio.Queue[str] = asyncio.Queue()

        # Tasks
        self.pipeline_tasks: List[asyncio.Task] = []
        self.current_llm_task: Optional[asyncio.Task] = None
        self.current_tts_task: Optional[asyncio.Task] = None

    def request_interrupt(self) -> None:
        """Request interruption of all processing"""
        logger.info(f"Interrupt requested: {self.session_id}")
        self.interrupt_requested = True
        self._cancel_pipeline_tasks()

    def clear_interrupt(self) -> None:
        """Clear interruption flag"""
        self.interrupt_requested = False

    def is_interrupted(self) -> bool:
        """Check if interruption is requested"""
        return self.interrupt_requested

    def update_activity(self) -> None:
        """Update last activity timestamp"""
        self.last_activity = time.time()

    def is_inactive(self, timeout_seconds: int = Config.SESSION_TIMEOUT) -> bool:
        """Check if session is inactive based on timeout"""
        return (time.time() - self.last_activity) > timeout_seconds

    def _cancel_pipeline_tasks(self) -> None:
        """Cancel all pipeline tasks and clear queues"""
        # Cancel task lists
        for task in self.pipeline_tasks:
            if not task.done():
                task.cancel()
        self.pipeline_tasks.clear()

        # Cancel individual tasks
        for task_attr in ['current_llm_task', 'current_tts_task']:
            task = getattr(self, task_attr)
            if task and not task.done():
                task.cancel()
                setattr(self, task_attr, None)

        # Clear all queues
        self._clear_queues()

    def _clear_queues(self) -> None:
        """Clear all pipeline queues efficiently

        Uses a bounded loop to avoid potential infinite loops in edge cases
        where items are added faster than removed.
        """
        for queue in [self.asr_queue, self.llm_queue, self.tts_queue]:
            # Get current queue size and clear that many items
            # This avoids race conditions with continuous queue.empty() checks
            items_to_clear = queue.qsize()
            for _ in range(items_to_clear):
                try:
                    queue.get_nowait()
                    queue.task_done()
                except asyncio.QueueEmpty:
                    break


# Global session dictionary
_sessions: Dict[str, SessionState] = {}


def get_session(session_id: str) -> SessionState:
    """Get or create session state (thread-safe)"""
    with _sessions_lock:
        if session_id not in _sessions:
            _sessions[session_id] = SessionState(session_id)
        # Update activity timestamp
        _sessions[session_id].update_activity()
        return _sessions[session_id]


def remove_session(session_id: str) -> None:
    """Remove a session (thread-safe)"""
    with _sessions_lock:
        if session_id in _sessions:
            del _sessions[session_id]
            logger.info(f"Session removed: {session_id}")


def get_all_sessions() -> Dict[str, SessionState]:
    """Get a copy of all active sessions (thread-safe)"""
    with _sessions_lock:
        return _sessions.copy()


async def cleanup_inactive_sessions() -> None:
    """Periodically clean up inactive sessions"""
    while True:
        try:
            await asyncio.sleep(60)  # Check every minute

            # Get inactive sessions with lock
            with _sessions_lock:
                inactive_session_ids = [
                    session_id
                    for session_id, state in _sessions.items()
                    if state.is_inactive()
                ]

            for session_id in inactive_session_ids:
                logger.info(f"Cleaning up inactive session: {session_id}")
                try:
                    session = get_session(session_id)
                    if session.tts_processor:
                        await session.tts_processor.interrupt()
                except Exception as e:
                    logger.error(f"Error interrupting TTS processor: {e}")

                remove_session(session_id)

        except Exception as e:
            logger.error(f"Session cleanup error: {e}")
            await asyncio.sleep(60)
