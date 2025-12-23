"""Unit tests for app.py - FastAPI application"""

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
        routes = [route.path for route in app.routes]
        assert any("/static" in str(route) for route in routes)
