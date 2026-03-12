"""FastAPI application entry point for WTI Trading Bot.

This module provides the main FastAPI application with:
- Lifespan context manager for startup/shutdown
- Middleware for CORS, request ID, and timing
- Exception handlers
- Graceful shutdown handling
- Prometheus metrics endpoint
"""

import asyncio
import time
import uuid
from contextlib import asynccontextmanager
from decimal import Decimal
from typing import Any, AsyncGenerator

from fastapi import FastAPI, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest

from src.api.events import set_event_engine
from src.api.execution import set_execution_engine
from src.api.market_data import set_feed_manager
from src.api.risk import set_risk_manager
from src.api.router import api_router
from src.api.signals import set_strategy_engine
from src.api.system import is_kill_switch_active
from src.config.settings import Settings, get_settings
from src.core.database import close_database, init_database
from src.core.logging_config import (
    clear_correlation_id,
    configure_logging,
    get_logger,
    set_correlation_id,
)
from src.core.redis_client import close_redis_client, get_redis_client
from src.core.secrets import init_secrets_manager
from src.core.security_middleware import (
    InputValidationMiddleware,
    RateLimitMiddleware,
    SecurityHeadersMiddleware,
)
from src.event_bus import EventBus, get_event_bus
from src.events.calendar import EventCalendar
from src.events.engine import EventEngine
from src.execution.brokers.paper import PaperBroker
from src.execution.engine import ExecutionEngine
from src.market_data.feed_manager import FeedManager
from src.market_data.adapters.simulated import SimulatedFeedAdapter
from src.risk.manager import RiskManager
from src.risk.models import RiskLimits
from src.dashboard import DashboardService, set_dashboard_service
from src.services.health_monitor import get_health_monitor
from src.strategy.engine import StrategyEngine
from src.websocket.manager import WebSocketManager
from src.websocket.handlers import (
    MarketDataHandler,
    SignalHandler,
    OrderHandler,
    PositionHandler,
    SystemStatusHandler,
)

# Prometheus metrics
REQUEST_COUNT = Counter(
    "http_requests_total",
    "Total HTTP requests",
    ["method", "endpoint", "status"],
)
REQUEST_DURATION = Histogram(
    "http_request_duration_seconds",
    "HTTP request duration in seconds",
    ["method", "endpoint"],
)
ACTIVE_CONNECTIONS = Counter(
    "http_active_connections",
    "Number of active HTTP connections",
)

logger = get_logger("system")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan context manager.

    Handles startup and shutdown events for the FastAPI application.
    This includes initializing database connections, Redis clients,
    and other resources.

    Args:
        app: FastAPI application instance.

    Yields:
        None
    """
    # Startup
    logger.info("Starting WTI Trading Bot...")

    settings = get_settings()

    # Configure logging
    configure_logging(settings)
    logger.info(
        "Application starting",
        version=settings.app_version,
        environment=settings.environment,
        trading_mode=settings.trading.mode,
    )

    # Initialize database
    try:
        await init_database(settings)
        logger.info("Database initialized successfully")
    except Exception as e:
        logger.error("Failed to initialize database", error=str(e))
        raise

    # Initialize Redis (non-critical, can operate without it)
    try:
        await get_redis_client(settings)
        logger.info("Redis client initialized")
    except Exception as e:
        logger.warning("Redis initialization failed, operating without cache", error=str(e))

    # Initialize secrets manager
    try:
        init_secrets_manager()
        logger.info("Secrets manager initialized")
    except Exception as e:
        logger.warning("Secrets manager initialization failed", error=str(e))

    # Start health monitoring
    health_monitor = get_health_monitor(settings)
    await health_monitor.start_periodic_checks()
    logger.info("Health monitoring started")

    # Initialize event bus
    event_bus = get_event_bus()
    await event_bus.start()
    logger.info("Event bus started")
    
    # Initialize WebSocket manager
    ws_manager = WebSocketManager()
    set_websocket_manager(ws_manager)
    logger.info("WebSocket manager initialized")
    
    # Initialize WebSocket handlers
    market_data_handler = MarketDataHandler(ws_manager)
    signal_handler = SignalHandler(ws_manager)
    order_handler = OrderHandler(ws_manager)
    position_handler = PositionHandler(ws_manager)
    system_status_handler = SystemStatusHandler(ws_manager)
    logger.info("WebSocket handlers initialized")

    # Initialize feed manager (with simulated feed for now)
    feed_manager = None
    if settings.features.enable_market_data:
        try:
            redis_client = await get_redis_client(settings)
            feed_manager = FeedManager(redis=redis_client)
            
            # Create simulated feed for testing
            simulated_feed = SimulatedFeedAdapter(
                feed_id="simulated-primary",
                symbols=["CL=F", "BZ=F", "DX-Y.NYB", "ES=F", "NQ=F"],
                config={
                    "volatility": 0.05,
                    "tick_interval_ms": 500,
                    "bar_interval_seconds": 60,
                },
            )
            
            feed_manager.register_feed(simulated_feed)
            await feed_manager.start()
            set_feed_manager(feed_manager)
            
            logger.info(
                "Feed manager initialized with simulated feed",
                symbols=simulated_feed.symbols,
            )
        except Exception as e:
            logger.error("Failed to initialize feed manager", error=str(e))
            # Continue without market data

    # Initialize strategy engine
    strategy_engine = None
    if settings.features.enable_signal_generation:
        try:
            strategy_engine = StrategyEngine(
                event_bus=event_bus,
                config={
                    "min_confidence": 65,
                    "sweep_lookback": 20,
                    "sweep_threshold": 0.05,
                    "reclaim_timeout": 30.0,
                    "consolidation_periods": 10,
                    "breakout_threshold": 0.3,
                    "correlation_lookback": 20,
                    "correlation_move_threshold": 0.3,
                },
            )
            
            # Connect feed manager to strategy engine
            if feed_manager:
                feed_manager.on_tick(strategy_engine.on_tick)
                feed_manager.on_bar(strategy_engine.on_bar)
            
            strategy_engine.start()
            set_strategy_engine(strategy_engine)
            
            logger.info("Strategy engine initialized")
        except Exception as e:
            logger.error("Failed to initialize strategy engine", error=str(e))
    
    # Initialize risk manager
    risk_manager = None
    if settings.features.enable_risk_management:
        try:
            risk_limits = RiskLimits(
                max_position_size=settings.risk.max_position_size,
                max_position_pct=Decimal(str(settings.risk.max_position_pct)),
                max_open_positions=settings.risk.max_open_positions,
                max_daily_loss=Decimal(str(settings.risk.max_daily_loss)),
                max_drawdown_pct=Decimal(str(settings.risk.max_drawdown_pct)),
                per_trade_risk=Decimal(str(settings.risk.per_trade_risk)),
                max_trades_per_day=settings.risk.max_trades_per_day,
                cooldown_after_loss_seconds=settings.risk.cooldown_seconds,
                kill_switch_enabled=settings.risk.kill_switch_enabled,
            )
            
            risk_manager = RiskManager(limits=risk_limits)
            set_risk_manager(risk_manager)
            
            logger.info("Risk manager initialized")
        except Exception as e:
            logger.error("Failed to initialize risk manager", error=str(e))

    # Initialize execution engine
    execution_engine = None
    if settings.features.enable_order_execution:
        try:
            # Create paper broker for now
            paper_broker = PaperBroker(
                initial_balance=Decimal("100000.00"),
                slippage_pct=0.01,
                latency_ms=50.0,
            )
            
            execution_engine = ExecutionEngine(
                broker=paper_broker,
                risk_manager=risk_manager,
                event_bus=event_bus,
            )
            
            await execution_engine.start()
            set_execution_engine(execution_engine)
            
            # Connect market data to broker
            if feed_manager:
                feed_manager.on_tick(paper_broker.on_market_tick)
            
            # Connect signals to execution
            if strategy_engine:
                strategy_engine.on_signal(lambda s: asyncio.create_task(execution_engine.execute_signal(s)))
            
            logger.info("Execution engine initialized with paper broker")
        except Exception as e:
            logger.error("Failed to initialize execution engine", error=str(e))

    # Initialize event engine
    event_engine = None
    if settings.features.enable_event_calendar:
        try:
            calendar = EventCalendar()
            
            event_engine = EventEngine(
                calendar=calendar,
                event_bus=event_bus,
                strategy_engine=strategy_engine,
                risk_manager=risk_manager,
            )
            
            # Initialize default schedule (EIA releases)
            event_engine.initialize_default_schedule(weeks=4)
            
            await event_engine.start()
            set_event_engine(event_engine)
            
            logger.info("Event engine initialized")
        except Exception as e:
            logger.error("Failed to initialize event engine", error=str(e))
    
    # Connect WebSocket handlers to components
    if feed_manager:
        feed_manager.on_tick(market_data_handler.on_tick)
        feed_manager.on_bar(market_data_handler.on_bar)
        logger.info("Market data handler connected")
    
    if strategy_engine:
        strategy_engine.on_signal(signal_handler.on_signal)
        logger.info("Signal handler connected")
    
    if execution_engine and execution_engine.broker:
        # Connect order and position handlers via event bus
        event_bus.subscribe("order_created", lambda o: order_handler.on_order_update(o))
        event_bus.subscribe("order_filled", lambda data: order_handler.on_fill(data["order"], data["fill"]))
        event_bus.subscribe("position_updated", lambda p: position_handler.on_position_update(p))
        logger.info("Order and position handlers connected")
    
    # Initialize dashboard service
    dashboard_service = DashboardService(
        feed_manager=feed_manager,
        strategy_engine=strategy_engine,
        execution_engine=execution_engine,
        risk_manager=risk_manager,
        event_engine=event_engine,
        ws_manager=ws_manager,
    )
    set_dashboard_service(dashboard_service)
    logger.info("Dashboard service initialized")
    
    logger.info("WTI Trading Bot started successfully")

    yield

    # Shutdown
    logger.info("Shutting down WTI Trading Bot...")

    # Stop event engine
    if event_engine:
        await event_engine.stop()
        logger.info("Event engine stopped")

    # Stop execution engine
    if execution_engine:
        await execution_engine.stop()
        logger.info("Execution engine stopped")

    # Stop strategy engine
    if strategy_engine:
        strategy_engine.stop()
        logger.info("Strategy engine stopped")

    # Stop feed manager
    if feed_manager:
        await feed_manager.stop()
        logger.info("Feed manager stopped")

    # Stop event bus
    await event_bus.stop()
    logger.info("Event bus stopped")

    # Stop health monitoring
    await health_monitor.stop_periodic_checks()
    logger.info("Health monitoring stopped")

    # Close Redis connection
    await close_redis_client()
    logger.info("Redis connection closed")

    # Close database connections
    await close_database()
    logger.info("Database connections closed")

    logger.info("WTI Trading Bot shutdown complete")


def create_application(settings: Settings | None = None) -> FastAPI:
    """Create and configure the FastAPI application.

    Args:
        settings: Application settings. If None, settings are loaded automatically.

    Returns:
        Configured FastAPI application instance.
    """
    settings = settings or get_settings()

    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        description="Production-grade WTI crude oil event-driven trading bot",
        docs_url="/docs" if not settings.is_production() else None,
        redoc_url="/redoc" if not settings.is_production() else None,
        openapi_url="/openapi.json" if not settings.is_production() else None,
        lifespan=lifespan,
    )

    # Add CORS middleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.get_cors_origins_list(),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Add security headers middleware
    app.add_middleware(
        SecurityHeadersMiddleware,
        allow_iframe=not settings.is_production(),
    )

    # Add input validation middleware
    app.add_middleware(
        InputValidationMiddleware,
        block_on_violation=True,
    )

    # Add rate limiting middleware (only in production)
    if settings.is_production():
        app.add_middleware(
            RateLimitMiddleware,
            requests_per_minute=settings.api.rate_limit_per_minute or 100,
            burst_size=20,
            use_distributed=True,
        )

    # Add request ID and timing middleware
    @app.middleware("http")
    async def request_middleware(request: Request, call_next: Any) -> Response:
        """Process each request with correlation ID and timing.

        Args:
            request: Incoming request.
            call_next: Next middleware/handler.

        Returns:
            Response from the handler.
        """
        start_time = time.perf_counter()

        # Set correlation ID
        correlation_id = request.headers.get("X-Correlation-ID", str(uuid.uuid4()))
        set_correlation_id(correlation_id)

        # Log request
        logger.info(
            "Request started",
            method=request.method,
            path=request.url.path,
            correlation_id=correlation_id,
            client_ip=request.client.host if request.client else None,
        )

        # Check kill switch for trading endpoints
        if request.url.path.startswith("/api/v1/orders") and is_kill_switch_active():
            return JSONResponse(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                content={
                    "error": "Trading halted",
                    "message": "Kill switch is active. Trading operations are disabled.",
                },
            )

        try:
            response = await call_next(request)

            # Calculate duration
            duration = time.perf_counter() - start_time

            # Record metrics
            REQUEST_COUNT.labels(
                method=request.method,
                endpoint=request.url.path,
                status=response.status_code,
            ).inc()
            REQUEST_DURATION.labels(
                method=request.method,
                endpoint=request.url.path,
            ).observe(duration)

            # Add correlation ID to response headers
            response.headers["X-Correlation-ID"] = correlation_id
            response.headers["X-Response-Time"] = f"{duration:.3f}s"

            # Log response
            logger.info(
                "Request completed",
                method=request.method,
                path=request.url.path,
                status_code=response.status_code,
                duration_ms=round(duration * 1000, 2),
                correlation_id=correlation_id,
            )

            return response

        except Exception as e:
            duration = time.perf_counter() - start_time
            logger.error(
                "Request failed",
                method=request.method,
                path=request.url.path,
                error=str(e),
                duration_ms=round(duration * 1000, 2),
                correlation_id=correlation_id,
            )
            raise

        finally:
            clear_correlation_id()

    # Include API routers
    app.include_router(api_router)
    
    # Include WebSocket routes (at root level)
    from src.api import websocket as websocket_router
    app.include_router(websocket_router.router)

    # Add exception handlers
    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        """Handle uncaught exceptions.

        Args:
            request: The request that caused the exception.
            exc: The exception that was raised.

        Returns:
            JSON response with error details.
        """
        logger.exception("Unhandled exception", exc_info=exc)
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "error": "Internal server error",
                "message": "An unexpected error occurred",
                "correlation_id": get_correlation_id(),
            },
        )

    @app.exception_handler(ValueError)
    async def value_error_handler(request: Request, exc: ValueError) -> JSONResponse:
        """Handle ValueError exceptions.

        Args:
            request: The request that caused the exception.
            exc: The ValueError that was raised.

        Returns:
            JSON response with error details.
        """
        logger.warning("Value error", error=str(exc))
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={
                "error": "Bad request",
                "message": str(exc),
                "correlation_id": get_correlation_id(),
            },
        )

    # Add root endpoint
    @app.get("/")
    async def root() -> dict[str, Any]:
        """Root endpoint with API information.

        Returns:
            Dictionary with API information.
        """
        return {
            "name": settings.app_name,
            "version": settings.app_version,
            "environment": settings.environment,
            "trading_mode": settings.trading.mode,
            "documentation": "/docs" if not settings.is_production() else None,
            "health": "/api/v1/health",
        }

    # Add metrics endpoint
    @app.get("/metrics")
    async def metrics() -> Response:
        """Prometheus metrics endpoint.

        Returns:
            Response with Prometheus metrics in text format.
        """
        return Response(
            content=generate_latest(),
            media_type=CONTENT_TYPE_LATEST,
        )

    return app


# Create the application instance
app = create_application()


def main() -> None:
    """Main entry point for running the application.

    This function is called when running the application directly
    or through the wti-bot CLI command.
    """
    import uvicorn

    settings = get_settings()

    uvicorn.run(
        "src.main:app",
        host=settings.api.host,
        port=settings.api.port,
        workers=settings.api.workers if not settings.api.reload else 1,
        reload=settings.api.reload,
        log_level=settings.log_level.lower(),
        access_log=not settings.is_production(),
    )


if __name__ == "__main__":
    main()
