"""Unit tests for session.py"""

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from session import (
    SessionState,
    _sessions,
    get_all_sessions,
    get_session,
    remove_session,
)


class TestSessionState:
    """Tests for SessionState class"""

    def test_init_with_session_id(self) -> None:
        """Test initialization with provided session_id"""
        session = SessionState("test-session-123")
        assert session.session_id == "test-session-123"
        assert session.is_processing_llm is False
        assert session.is_tts_active is False
        assert session.interrupt_requested is False

    def test_init_without_session_id(self) -> None:
        """Test initialization generates UUID"""
        session = SessionState()
        assert session.session_id is not None
        assert len(session.session_id) == 36  # UUID format

    def test_request_interrupt(self) -> None:
        """Test interrupt request"""
        session = SessionState("test-session")
        assert session.is_interrupted() is False
        session.request_interrupt()
        assert session.is_interrupted() is True

    def test_clear_interrupt(self) -> None:
        """Test clearing interrupt flag"""
        session = SessionState("test-session")
        session.request_interrupt()
        assert session.is_interrupted() is True
        session.clear_interrupt()
        assert session.is_interrupted() is False

    def test_update_activity(self) -> None:
        """Test activity timestamp update"""
        session = SessionState("test-session")
        old_time = session.last_activity
        time.sleep(0.1)
        session.update_activity()
        assert session.last_activity > old_time

    def test_is_inactive(self) -> None:
        """Test inactive check"""
        session = SessionState("test-session")
        # Should not be inactive immediately
        assert session.is_inactive(timeout_seconds=1) is False
        # Manually set old timestamp
        session.last_activity = time.time() - 10
        assert session.is_inactive(timeout_seconds=5) is True

    def test_queues_initialized(self) -> None:
        """Test that queues are properly initialized"""
        session = SessionState("test-session")
        assert isinstance(session.asr_queue, asyncio.Queue)
        assert isinstance(session.llm_queue, asyncio.Queue)
        assert isinstance(session.tts_queue, asyncio.Queue)

    @pytest.mark.asyncio
    async def test_clear_queues(self) -> None:
        """Test clearing queues"""
        session = SessionState("test-session")
        await session.asr_queue.put("test1")
        await session.llm_queue.put("test2")
        await session.tts_queue.put("test3")

        assert not session.asr_queue.empty()
        session._clear_queues()
        assert session.asr_queue.empty()
        assert session.llm_queue.empty()
        assert session.tts_queue.empty()

    def test_cancel_pipeline_tasks_empty(self) -> None:
        """Test canceling pipeline tasks when empty"""
        session = SessionState("test-session")
        # Should not raise error
        session._cancel_pipeline_tasks()
        assert session.pipeline_tasks == []

    def test_cancel_pipeline_tasks_with_tasks(self) -> None:
        """Test canceling pipeline tasks with active tasks"""
        session = SessionState("test-session")

        # Create mock tasks
        mock_task1 = MagicMock()
        mock_task1.done.return_value = False
        mock_task2 = MagicMock()
        mock_task2.done.return_value = True  # Already done

        session.pipeline_tasks = [mock_task1, mock_task2]

        session._cancel_pipeline_tasks()

        mock_task1.cancel.assert_called_once()
        mock_task2.cancel.assert_not_called()  # Already done
        assert session.pipeline_tasks == []

    def test_cancel_pipeline_tasks_with_llm_task(self) -> None:
        """Test canceling LLM task"""
        session = SessionState("test-session")

        mock_llm_task = MagicMock()
        mock_llm_task.done.return_value = False
        session.current_llm_task = mock_llm_task

        session._cancel_pipeline_tasks()

        mock_llm_task.cancel.assert_called_once()
        assert session.current_llm_task is None

    def test_cancel_pipeline_tasks_with_tts_task(self) -> None:
        """Test canceling TTS task"""
        session = SessionState("test-session")

        mock_tts_task = MagicMock()
        mock_tts_task.done.return_value = False
        session.current_tts_task = mock_tts_task

        session._cancel_pipeline_tasks()

        mock_tts_task.cancel.assert_called_once()
        assert session.current_tts_task is None

    def test_cancel_pipeline_tasks_with_done_llm_task(self) -> None:
        """Test that done LLM task is not canceled"""
        session = SessionState("test-session")

        mock_llm_task = MagicMock()
        mock_llm_task.done.return_value = True
        session.current_llm_task = mock_llm_task

        session._cancel_pipeline_tasks()

        mock_llm_task.cancel.assert_not_called()


class TestSessionManagement:
    """Tests for session management functions"""

    def setup_method(self) -> None:
        """Clear sessions before each test"""
        _sessions.clear()

    def teardown_method(self) -> None:
        """Clear sessions after each test"""
        _sessions.clear()

    def test_get_session_creates_new(self) -> None:
        """Test get_session creates new session"""
        session = get_session("new-session-id")
        assert session is not None
        assert session.session_id == "new-session-id"
        assert "new-session-id" in _sessions

    def test_get_session_returns_existing(self) -> None:
        """Test get_session returns existing session"""
        session1 = get_session("existing-session")
        session2 = get_session("existing-session")
        assert session1 is session2

    def test_get_session_updates_activity(self) -> None:
        """Test get_session updates activity timestamp"""
        session = get_session("activity-test")
        old_time = session.last_activity
        time.sleep(0.1)
        get_session("activity-test")
        assert session.last_activity > old_time

    def test_remove_session(self) -> None:
        """Test removing a session"""
        get_session("to-be-removed")
        assert "to-be-removed" in _sessions
        remove_session("to-be-removed")
        assert "to-be-removed" not in _sessions

    def test_remove_nonexistent_session(self) -> None:
        """Test removing nonexistent session doesn't raise error"""
        remove_session("nonexistent")  # Should not raise

    def test_get_all_sessions(self) -> None:
        """Test getting all sessions"""
        get_session("session-1")
        get_session("session-2")
        get_session("session-3")
        all_sessions = get_all_sessions()
        assert len(all_sessions) == 3
        assert "session-1" in all_sessions
        assert "session-2" in all_sessions
        assert "session-3" in all_sessions


class TestCleanupInactiveSessions:
    """Tests for cleanup_inactive_sessions function"""

    def setup_method(self) -> None:
        """Clear sessions before each test"""
        _sessions.clear()

    def teardown_method(self) -> None:
        """Clear sessions after each test"""
        _sessions.clear()

    @pytest.mark.asyncio
    async def test_cleanup_removes_inactive_sessions(self) -> None:
        """Test that cleanup removes inactive sessions"""
        from session import cleanup_inactive_sessions

        # Create a session and make it inactive
        session = get_session("inactive-session")
        session.last_activity = time.time() - 1000  # Very old

        # Run cleanup briefly
        with patch("session.asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            # Make sleep raise after first iteration
            mock_sleep.side_effect = [None, asyncio.CancelledError()]

            try:
                await cleanup_inactive_sessions()
            except asyncio.CancelledError:
                pass

        # Session should be removed
        assert "inactive-session" not in _sessions

    @pytest.mark.asyncio
    async def test_cleanup_keeps_active_sessions(self) -> None:
        """Test that cleanup keeps active sessions"""
        from session import cleanup_inactive_sessions

        # Create an active session
        session = get_session("active-session")
        session.last_activity = time.time()  # Just now

        with patch("session.asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            mock_sleep.side_effect = [None, asyncio.CancelledError()]

            try:
                await cleanup_inactive_sessions()
            except asyncio.CancelledError:
                pass

        # Session should still exist
        assert "active-session" in _sessions

    @pytest.mark.asyncio
    async def test_cleanup_handles_tts_interrupt_error(self) -> None:
        """Test cleanup handles TTS interrupt errors gracefully"""
        from session import cleanup_inactive_sessions

        # Create an inactive session with TTS processor
        session = get_session("session-with-tts")
        session.last_activity = time.time() - 1000
        mock_tts = AsyncMock()
        mock_tts.interrupt.side_effect = Exception("TTS error")
        session.tts_processor = mock_tts

        with patch("session.asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            mock_sleep.side_effect = [None, asyncio.CancelledError()]

            try:
                await cleanup_inactive_sessions()
            except asyncio.CancelledError:
                pass

        # Session should be removed despite TTS error
        assert "session-with-tts" not in _sessions
