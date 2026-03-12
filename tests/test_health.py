"""Tests for health check endpoints.

This module contains tests for the health check API endpoints including:
- Overall health check
- Readiness probe
- Liveness probe
- Database health check
- Redis health check
"""

import pytest
from httpx import ASGITransport, AsyncClient

from src.config.settings import Settings, get_settings
from src.main import create_application


@pytest.fixture
def test_settings() -> Settings:
    """Create test settings fixture."""
    return Settings(
        environment="testing",
        debug=True,
        log_level="DEBUG",
        database__async_url="postgresql+asyncpg://test:test@localhost:5432/test_wti",
        database__sync_url="postgresql://test:test@localhost:5432/test_wti",
        redis__url="redis://localhost:6379/1",
    )


@pytest.fixture
async def test_client(test_settings: Settings) -> AsyncClient:
    """Create test client fixture."""
    app = create_application(test_settings)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


class TestHealthEndpoints:
    """Test cases for health check endpoints."""

    @pytest.mark.asyncio
    async def test_health_endpoint_exists(self, test_client: AsyncClient) -> None:
        """Test that health endpoint exists and returns valid response."""
        response = await test_client.get("/api/v1/health/")
        # Should return 200 or 503 depending on database connectivity
        assert response.status_code in [200, 503]
        
        data = response.json()
        assert "status" in data
        assert "timestamp" in data
        assert "version" in data
        assert "environment" in data
        assert "checks" in data

    @pytest.mark.asyncio
    async def test_health_response_structure(self, test_client: AsyncClient) -> None:
        """Test health response has correct structure."""
        response = await test_client.get("/api/v1/health/")
        data = response.json()
        
        # Verify required fields
        assert isinstance(data.get("status"), str)
        assert isinstance(data.get("timestamp"), str)
        assert isinstance(data.get("version"), str)
        assert isinstance(data.get("environment"), str)
        assert isinstance(data.get("checks"), dict)

    @pytest.mark.asyncio
    async def test_health_status_values(self, test_client: AsyncClient) -> None:
        """Test that health status is one of expected values."""
        response = await test_client.get("/api/v1/health/")
        data = response.json()
        
        valid_statuses = ["healthy", "degraded", "unhealthy"]
        assert data["status"] in valid_statuses

    @pytest.mark.asyncio
    async def test_readiness_endpoint(self, test_client: AsyncClient) -> None:
        """Test readiness probe endpoint."""
        response = await test_client.get("/api/v1/health/ready")
        
        # Should return 200 or 503
        assert response.status_code in [200, 503]
        
        data = response.json()
        assert "ready" in data
        assert isinstance(data["ready"], bool)
        assert "timestamp" in data
        assert "dependencies" in data
        assert isinstance(data["dependencies"], dict)

    @pytest.mark.asyncio
    async def test_liveness_endpoint(self, test_client: AsyncClient) -> None:
        """Test liveness probe endpoint."""
        response = await test_client.get("/api/v1/health/live")
        
        assert response.status_code == 200
        
        data = response.json()
        assert "alive" in data
        assert data["alive"] is True
        assert "timestamp" in data
        assert "uptime_seconds" in data
        assert isinstance(data["uptime_seconds"], float)

    @pytest.mark.asyncio
    async def test_db_health_endpoint(self, test_client: AsyncClient) -> None:
        """Test database health check endpoint."""
        response = await test_client.get("/api/v1/health/db")
        
        # Should return 200 or 503 depending on database connectivity
        assert response.status_code in [200, 503]
        
        data = response.json()
        assert "status" in data
        assert "response_time_ms" in data
        assert isinstance(data["response_time_ms"], (int, float))

    @pytest.mark.asyncio
    async def test_redis_health_endpoint(self, test_client: AsyncClient) -> None:
        """Test Redis health check endpoint."""
        response = await test_client.get("/api/v1/health/redis")
        
        # Should return 200 or 503 depending on Redis connectivity
        assert response.status_code in [200, 503]
        
        data = response.json()
        assert "status" in data
        assert "response_time_ms" in data

    @pytest.mark.asyncio
    async def test_health_endpoint_correlation_id(self, test_client: AsyncClient) -> None:
        """Test that health endpoint accepts and returns correlation ID."""
        correlation_id = "test-correlation-id-123"
        response = await test_client.get(
            "/api/v1/health/",
            headers={"X-Correlation-ID": correlation_id}
        )
        
        # Verify correlation ID is returned in response headers
        assert response.headers.get("X-Correlation-ID") == correlation_id


class TestRootEndpoint:
    """Test cases for root endpoint."""

    @pytest.mark.asyncio
    async def test_root_endpoint(self, test_client: AsyncClient) -> None:
        """Test root endpoint returns API information."""
        response = await test_client.get("/")
        
        assert response.status_code == 200
        
        data = response.json()
        assert "name" in data
        assert "version" in data
        assert "environment" in data
        assert "trading_mode" in data


class TestMetricsEndpoint:
    """Test cases for Prometheus metrics endpoint."""

    @pytest.mark.asyncio
    async def test_metrics_endpoint(self, test_client: AsyncClient) -> None:
        """Test metrics endpoint returns Prometheus format."""
        response = await test_client.get("/metrics")
        
        assert response.status_code == 200
        assert "text/plain" in response.headers.get("content-type", "")
        
        # Check for expected metrics
        content = response.text
        assert "http_requests_total" in content or "python_info" in content


class TestSystemEndpoints:
    """Test cases for system endpoints."""

    @pytest.mark.asyncio
    async def test_system_status_endpoint(self, test_client: AsyncClient) -> None:
        """Test system status endpoint."""
        response = await test_client.get("/api/v1/system/status")
        
        assert response.status_code == 200
        
        data = response.json()
        assert "status" in data
        assert "version" in data
        assert "environment" in data
        assert "trading_mode" in data
        assert "kill_switch_triggered" in data
        assert "features" in data

    @pytest.mark.asyncio
    async def test_system_config_endpoint(self, test_client: AsyncClient) -> None:
        """Test system config endpoint returns safe config."""
        response = await test_client.get("/api/v1/system/config")
        
        assert response.status_code == 200
        
        data = response.json()
        # Verify no sensitive data is exposed
        assert "app_name" in data
        assert "app_version" in data
        assert "environment" in data
        assert "database_pool_size" in data
        # Ensure no passwords or URLs with credentials
        assert "password" not in str(data).lower()
        assert "secret" not in str(data).lower()

    @pytest.mark.asyncio
    async def test_system_version_endpoint(self, test_client: AsyncClient) -> None:
        """Test version endpoint."""
        response = await test_client.get("/api/v1/system/version")
        
        assert response.status_code == 200
        
        data = response.json()
        assert "version" in data
        assert "python_version" in data
        assert "platform" in data

    @pytest.mark.asyncio
    async def test_kill_switch_endpoint(self, test_client: AsyncClient) -> None:
        """Test kill switch endpoint."""
        # First check current status
        response = await test_client.get("/api/v1/system/kill-switch")
        assert response.status_code == 200
        
        data = response.json()
        assert "active" in data
        
        # Try to trigger kill switch
        response = await test_client.post(
            "/api/v1/system/kill-switch",
            json={"reason": "Test kill switch", "confirm": True}
        )
        
        # Should succeed or fail based on kill switch configuration
        assert response.status_code in [200, 403]
        
        if response.status_code == 200:
            data = response.json()
            assert data["triggered"] is True
            assert "timestamp" in data
            assert "reason" in data

    @pytest.mark.asyncio
    async def test_kill_switch_without_confirmation(self, test_client: AsyncClient) -> None:
        """Test kill switch requires confirmation."""
        response = await test_client.post(
            "/api/v1/system/kill-switch",
            json={"reason": "Test without confirmation", "confirm": False}
        )
        
        assert response.status_code == 400

    @pytest.mark.asyncio
    async def test_kill_switch_reset_endpoint(self, test_client: AsyncClient) -> None:
        """Test kill switch reset endpoint."""
        response = await test_client.post("/api/v1/system/kill-switch/reset")
        
        # Should succeed or fail based on current state
        assert response.status_code in [200, 400]
