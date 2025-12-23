"""Unit tests for session.py"""

import asyncio
import time

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
