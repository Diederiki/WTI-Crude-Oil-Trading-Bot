"""Application settings using Pydantic Settings.

This module provides centralized configuration management for the WTI Trading Bot.
All settings are loaded from environment variables with the WTI_ prefix.
"""

from functools import lru_cache
from typing import Literal, Self

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class DatabaseConfig(BaseSettings):
    """Database connection configuration."""

    model_config = SettingsConfigDict(
        env_prefix="WTI_DATABASE__",
        extra="ignore",
    )

    async_url: str = Field(
        default="postgresql+asyncpg://wti_user:wti_password@localhost:5432/wti_trading",
        description="Async PostgreSQL connection URL using asyncpg driver",
    )
    sync_url: str = Field(
        default="postgresql://wti_user:wti_password@localhost:5432/wti_trading",
        description="Sync PostgreSQL connection URL for migrations",
    )
    pool_size: int = Field(
        default=20,
        ge=1,
        le=100,
        description="Number of persistent connections in the pool",
    )
    max_overflow: int = Field(
        default=10,
        ge=0,
        le=50,
        description="Maximum number of overflow connections",
    )
    pool_timeout: int = Field(
        default=30,
        ge=1,
        le=300,
        description="Seconds to wait for a connection from the pool",
    )
    pool_recycle: int = Field(
        default=3600,
        ge=60,
        le=86400,
        description="Seconds after which to recycle connections",
    )
    echo: bool = Field(
        default=False,
        description="Enable SQL statement logging",
    )

    @field_validator("async_url")
    @classmethod
    def validate_async_url(cls, v: str) -> str:
        """Validate async URL uses asyncpg driver."""
        if not v.startswith("postgresql+asyncpg://"):
            raise ValueError("async_url must use postgresql+asyncpg:// driver")
        return v

    @field_validator("sync_url")
    @classmethod
    def validate_sync_url(cls, v: str) -> str:
        """Validate sync URL uses standard driver."""
        if not v.startswith("postgresql://"):
            raise ValueError("sync_url must use postgresql:// driver")
        return v


class RedisConfig(BaseSettings):
    """Redis connection configuration."""

    model_config = SettingsConfigDict(
        env_prefix="WTI_REDIS__",
        extra="ignore",
    )

    url: str = Field(
        default="redis://localhost:6379/0",
        description="Redis connection URL",
    )
    host: str = Field(
        default="localhost",
        description="Redis server hostname",
    )
    port: int = Field(
        default=6379,
        ge=1,
        le=65535,
        description="Redis server port",
    )
    db: int = Field(
        default=0,
        ge=0,
        le=15,
        description="Redis database number",
    )
    password: str | None = Field(
        default=None,
        description="Redis password (optional)",
    )
    ssl: bool = Field(
        default=False,
        description="Use SSL/TLS connection",
    )
    pool_size: int = Field(
        default=50,
        ge=1,
        le=500,
        description="Connection pool size",
    )
    socket_timeout: int = Field(
        default=5,
        ge=1,
        le=60,
        description="Socket timeout in seconds",
    )
    socket_connect_timeout: int = Field(
        default=5,
        ge=1,
        le=60,
        description="Socket connection timeout in seconds",
    )
    health_check_interval: int = Field(
        default=30,
        ge=5,
        le=300,
        description="Health check interval in seconds",
    )
    key_prefix: str = Field(
        default="wti",
        description="Key prefix for namespacing",
    )


class APIConfig(BaseSettings):
    """API server configuration."""

    model_config = SettingsConfigDict(
        env_prefix="WTI_API__",
        extra="ignore",
    )

    host: str = Field(
        default="0.0.0.0",
        description="Server bind address",
    )
    port: int = Field(
        default=8000,
        ge=1,
        le=65535,
        description="Server port",
    )
    workers: int = Field(
        default=1,
        ge=1,
        le=32,
        description="Number of worker processes",
    )
    reload: bool = Field(
        default=False,
        description="Enable auto-reload for development",
    )
    timeout_keep_alive: int = Field(
        default=5,
        ge=1,
        le=300,
        description="Keep-alive timeout in seconds",
    )
    rate_limit_per_minute: int = Field(
        default=100,
        ge=10,
        le=10000,
        description="API rate limit per minute per client",
    )
    api_keys: list[str] = Field(
        default_factory=list,
        description="List of valid API keys for authentication",
    )


class TradingConfig(BaseSettings):
    """Trading operation configuration."""

    model_config = SettingsConfigDict(
        env_prefix="WTI_TRADING__",
        extra="ignore",
    )

    mode: Literal["paper", "live"] = Field(
        default="paper",
        description="Trading mode: paper (simulated) or live (real)",
    )
    default_symbol: str = Field(
        default="CL=F",
        description="Default WTI crude oil symbol",
    )
    default_exchange: str = Field(
        default="NYMEX",
        description="Default exchange",
    )
    default_currency: str = Field(
        default="USD",
        description="Trading currency",
    )
    max_position_size: int = Field(
        default=100,
        ge=1,
        le=10000,
        description="Maximum position size in contracts",
    )
    default_order_qty: int = Field(
        default=10,
        ge=1,
        le=1000,
        description="Default order quantity",
    )
    timezone: str = Field(
        default="America/New_York",
        description="Trading timezone",
    )


class RiskConfig(BaseSettings):
    """Risk management configuration."""

    model_config = SettingsConfigDict(
        env_prefix="WTI_RISK__",
        extra="ignore",
    )

    max_daily_loss: float = Field(
        default=10000.0,
        ge=0,
        description="Maximum daily loss limit in account currency",
    )
    max_position_pct: float = Field(
        default=10.0,
        ge=0.1,
        le=100.0,
        description="Maximum position size as percentage of portfolio",
    )
    max_drawdown_pct: float = Field(
        default=5.0,
        ge=0.1,
        le=50.0,
        description="Maximum drawdown percentage before trading halt",
    )
    per_trade_risk: float = Field(
        default=500.0,
        ge=0,
        description="Per-trade risk limit in account currency",
    )
    max_open_positions: int = Field(
        default=5,
        ge=1,
        le=100,
        description="Maximum number of open positions",
    )
    max_orders_per_minute: int = Field(
        default=10,
        ge=1,
        le=1000,
        description="Maximum orders per minute (rate limiting)",
    )
    kill_switch_enabled: bool = Field(
        default=True,
        description="Enable emergency kill switch",
    )


class FeedConfig(BaseSettings):
    """Market data feed configuration."""

    model_config = SettingsConfigDict(
        env_prefix="WTI_FEED__",
        extra="ignore",
    )

    primary_provider: str = Field(
        default="polygon",
        description="Primary market data provider",
    )
    reconnect_attempts: int = Field(
        default=10,
        ge=1,
        le=100,
        description="Number of reconnection attempts",
    )
    reconnect_delay: float = Field(
        default=5.0,
        ge=0.1,
        le=60.0,
        description="Delay between reconnection attempts in seconds",
    )
    heartbeat_interval: float = Field(
        default=30.0,
        ge=5.0,
        le=300.0,
        description="Heartbeat interval in seconds",
    )
    tick_buffer_size: int = Field(
        default=1000,
        ge=100,
        le=10000,
        description="Tick buffer size for aggregation",
    )
    bar_interval_seconds: int = Field(
        default=60,
        ge=1,
        le=3600,
        description="Bar aggregation interval in seconds",
    )


class MetricsConfig(BaseSettings):
    """Metrics and monitoring configuration."""

    model_config = SettingsConfigDict(
        env_prefix="WTI_METRICS__",
        extra="ignore",
    )

    port: int = Field(
        default=9090,
        ge=1,
        le=65535,
        description="Prometheus metrics port",
    )
    path: str = Field(
        default="/metrics",
        description="Metrics endpoint path",
    )


class HealthConfig(BaseSettings):
    """Health check configuration."""

    model_config = SettingsConfigDict(
        env_prefix="WTI_HEALTH__",
        extra="ignore",
    )

    check_interval: int = Field(
        default=30,
        ge=5,
        le=300,
        description="Health check interval in seconds",
    )
    timeout: int = Field(
        default=5,
        ge=1,
        le=60,
        description="Health check timeout in seconds",
    )


class FeaturesConfig(BaseSettings):
    """Feature flags configuration."""

    model_config = SettingsConfigDict(
        env_prefix="WTI_FEATURES__",
        extra="ignore",
    )

    enable_websocket: bool = Field(default=True, description="Enable WebSocket connections")
    enable_market_data: bool = Field(default=True, description="Enable market data processing")
    enable_signal_generation: bool = Field(default=True, description="Enable signal generation")
    enable_order_execution: bool = Field(default=True, description="Enable order execution")
    enable_risk_checks: bool = Field(default=True, description="Enable risk management checks")


class Settings(BaseSettings):
    """Main application settings.

    All settings are loaded from environment variables with the WTI_ prefix.
    Nested configuration is supported using double underscore separator.

    Example:
        WTI_DATABASE__POOL_SIZE=20
        WTI_TRADING__MODE=paper
    """

    model_config = SettingsConfigDict(
        env_prefix="WTI_",
        env_nested_delimiter="__",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        validate_default=True,
    )

    # Application info
    app_name: str = Field(default="WTI Trading Bot", description="Application name")
    app_version: str = Field(default="0.1.0", description="Application version")
    debug: bool = Field(default=False, description="Debug mode")
    environment: Literal["development", "staging", "production"] = Field(
        default="development",
        description="Deployment environment",
    )
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = Field(
        default="INFO",
        description="Logging level",
    )
    log_format: Literal["json", "console"] = Field(
        default="json",
        description="Log output format",
    )

    # CORS origins
    cors_origins: str = Field(
        default="http://localhost:3000,http://localhost:8000",
        description="Comma-separated list of allowed CORS origins",
    )

    # Nested configurations
    database: DatabaseConfig = Field(default_factory=DatabaseConfig)
    redis: RedisConfig = Field(default_factory=RedisConfig)
    api: APIConfig = Field(default_factory=APIConfig)
    trading: TradingConfig = Field(default_factory=TradingConfig)
    risk: RiskConfig = Field(default_factory=RiskConfig)
    feed: FeedConfig = Field(default_factory=FeedConfig)
    metrics: MetricsConfig = Field(default_factory=MetricsConfig)
    health: HealthConfig = Field(default_factory=HealthConfig)
    features: FeaturesConfig = Field(default_factory=FeaturesConfig)

    @field_validator("cors_origins")
    @classmethod
    def parse_cors_origins(cls, v: str) -> str:
        """Validate CORS origins format."""
        if not v:
            return ""
        origins = [origin.strip() for origin in v.split(",")]
        for origin in origins:
            if not origin.startswith(("http://", "https://")):
                raise ValueError(f"Invalid CORS origin: {origin}")
        return v

    @model_validator(mode="after")
    def validate_live_trading(self) -> Self:
        """Validate live trading configuration."""
        if self.trading.mode == "live" and self.environment == "development":
            raise ValueError("Live trading not allowed in development environment")
        return self

    def get_cors_origins_list(self) -> list[str]:
        """Get CORS origins as a list.

        Returns:
            List of allowed CORS origin URLs.
        """
        if not self.cors_origins:
            return []
        return [origin.strip() for origin in self.cors_origins.split(",")]

    def is_production(self) -> bool:
        """Check if running in production environment.

        Returns:
            True if environment is production.
        """
        return self.environment == "production"

    def is_paper_trading(self) -> bool:
        """Check if running in paper trading mode.

        Returns:
            True if trading mode is paper.
        """
        return self.trading.mode == "paper"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Get cached application settings instance.

    This function uses LRU caching to avoid reloading settings
    on every call. Settings are loaded once at startup.

    Returns:
        Settings instance with all configuration values.

    Example:
        >>> settings = get_settings()
        >>> print(settings.database.async_url)
        >>> print(settings.trading.mode)
    """
    return Settings()


def reload_settings() -> Settings:
    """Reload and return fresh application settings.

    This function clears the cache and reloads settings from
    environment variables. Useful for testing or when settings
    need to be refreshed.

    Returns:
        Fresh Settings instance.
    """
    get_settings.cache_clear()
    return get_settings()
