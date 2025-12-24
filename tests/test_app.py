"""Unit tests for app.py - FastAPI application"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient


class TestHealthCheck:
    """Tests for health check endpoint"""

    def test_health_check(self) -> None:
        """Test health check returns OK"""
        from app import create_app

        app = create_app()
        client = TestClient(app)
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"


class TestRootEndpoint:
    """Tests for root endpoint"""

    def test_root_returns_html(self) -> None:
        """Test root endpoint returns HTML"""
        from app import create_app

        app = create_app()
        client = TestClient(app)
        response = client.get("/")
        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]


class TestStaticFiles:
    """Tests for static files serving"""

    def test_static_files_mounted(self) -> None:
        """Test static files are properly mounted"""
        from app import create_app

        app = create_app()
        # Check that /static route exists
        routes = [getattr(route, "path", str(route)) for route in app.routes]
        assert any("/static" in str(route) for route in routes)


class TestConfigureLogger:
    """Tests for configure_logger function"""

    def test_configure_logger(self) -> None:
        """Test logger configuration"""
        from app import configure_logger

        # Should not raise any exceptions
        configure_logger()


class TestLifespan:
    """Tests for application lifespan"""

    def test_lifespan_context_manager_exists(self) -> None:
        """Test lifespan context manager is properly defined"""
        from app import lifespan

        # Verify it's an async context manager
        assert callable(lifespan)

    @pytest.mark.asyncio
    async def test_create_app_with_lifespan(self) -> None:
        """Test that app is created with lifespan"""
        from app import create_app

        app = create_app()
        # App should have a lifespan configured
        assert app.router.lifespan_context is not None


class TestCreateApp:
    """Tests for create_app function"""

    def test_create_app_returns_fastapi(self) -> None:
        """Test create_app returns FastAPI instance"""
        from fastapi import FastAPI

        from app import create_app

        app = create_app()
        assert isinstance(app, FastAPI)

    def test_create_app_has_title(self) -> None:
        """Test app has correct title"""
        from app import create_app

        app = create_app()
        assert app.title == "Realtime AI Chat API"

    def test_create_app_has_routes(self) -> None:
        """Test app has expected routes"""
        from app import create_app

        app = create_app()
        route_paths = [getattr(route, "path", "") for route in app.routes]

        assert "/" in route_paths
        assert "/health" in route_paths
        assert "/ws" in route_paths


class TestWebSocketEndpoint:
    """Tests for WebSocket endpoint"""

    @pytest.mark.asyncio
    async def test_websocket_endpoint_calls_handler(self) -> None:
        """Test websocket_endpoint calls handle_websocket_connection"""
        from app import websocket_endpoint

        mock_websocket = MagicMock()

        with patch("app.handle_websocket_connection", new_callable=AsyncMock) as mock_handler:
            await websocket_endpoint(mock_websocket)
            mock_handler.assert_called_once_with(mock_websocket)
