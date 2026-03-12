"""Structured logging configuration for production environments.

This module provides JSON-formatted structured logging suitable for
production deployments with log aggregation systems. It supports:
- JSON structured logs for production
- Human-readable console logs for development
- Separate loggers for different subsystems
- Correlation ID tracking for request tracing
- Log rotation and proper log levels
"""

import logging
import logging.handlers
import sys
import uuid
from contextvars import ContextVar
from typing import Any

import structlog
from pythonjsonlogger import jsonlogger

from src.config.settings import Settings

# Context variable for correlation ID tracking
correlation_id_var: ContextVar[str] = ContextVar(
    "correlation_id",
    default="",
)

# Logger names for different subsystems
LOGGER_NAMES = {
    "market_data": "wti.market_data",
    "signals": "wti.signals",
    "orders": "wti.orders",
    "risk": "wti.risk",
    "system": "wti.system",
    "api": "wti.api",
    "database": "wti.database",
    "redis": "wti.redis",
}


class CorrelationIdFilter(logging.Filter):
    """Logging filter that adds correlation ID to log records."""

    def filter(self, record: logging.LogRecord) -> bool:
        """Add correlation ID to the log record.

        Args:
            record: The log record to process.

        Returns:
            Always True to include the record.
        """
        record.correlation_id = correlation_id_var.get() or "-"
        return True


def get_correlation_id() -> str:
    """Get the current correlation ID.

    Returns:
        The current correlation ID or empty string if not set.
    """
    return correlation_id_var.get()


def set_correlation_id(correlation_id: str | None = None) -> str:
    """Set the correlation ID for the current context.

    Args:
        correlation_id: The correlation ID to set. If None, a new UUID is generated.

    Returns:
        The correlation ID that was set.
    """
    cid = correlation_id or str(uuid.uuid4())
    correlation_id_var.set(cid)
    return cid


def clear_correlation_id() -> None:
    """Clear the current correlation ID."""
    correlation_id_var.set("")


def _setup_json_formatter() -> jsonlogger.JsonFormatter:
    """Create JSON formatter for structured logging.

    Returns:
        Configured JSON formatter instance.
    """
    return jsonlogger.JsonFormatter(
        fmt="%(timestamp)s %(level)s %(name)s %(message)s %(correlation_id)s",
        rename_fields={
            "levelname": "level",
            "asctime": "timestamp",
        },
        timestamp=True,
    )


def _setup_console_formatter() -> logging.Formatter:
    """Create human-readable console formatter.

    Returns:
        Configured console formatter instance.
    """
    return logging.Formatter(
        fmt="%(asctime)s | %(levelname)-8s | %(name)s | %(correlation_id)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def _configure_standard_logging(settings: Settings) -> None:
    """Configure Python's standard logging.

    Args:
        settings: Application settings.
    """
    # Determine log format and level
    use_json = settings.log_format == "json" or settings.is_production()
    log_level = getattr(logging, settings.log_level.upper(), logging.INFO)

    # Create root handler
    root_handler = logging.StreamHandler(sys.stdout)
    root_handler.setLevel(log_level)
    root_handler.addFilter(CorrelationIdFilter())

    if use_json:
        root_handler.setFormatter(_setup_json_formatter())
    else:
        root_handler.setFormatter(_setup_console_formatter())

    # Configure root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)
    root_logger.handlers = [root_handler]

    # Reduce noise from third-party libraries
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
    logging.getLogger("redis").setLevel(logging.WARNING)

    # Enable SQL echo if configured
    if settings.database.echo:
        logging.getLogger("sqlalchemy.engine").setLevel(logging.INFO)


def _configure_structlog(settings: Settings) -> None:
    """Configure structlog for structured logging.

    Args:
        settings: Application settings.
    """
    use_json = settings.log_format == "json" or settings.is_production()

    # Processors for structlog
    shared_processors: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.stdlib.add_logger_name,
        structlog.stdlib.ExtraAdder(),
    ]

    if use_json:
        # JSON output for production
        processors = shared_processors + [
            structlog.processors.dict_tracebacks,
            structlog.processors.JSONRenderer(),
        ]
    else:
        # Console output for development
        processors = shared_processors + [
            structlog.dev.ConsoleRenderer(
                colors=True,
                sort_keys=False,
            ),
        ]

    structlog.configure(
        processors=processors,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )


def configure_logging(settings: Settings | None = None) -> None:
    """Configure logging for the application.

    This function sets up both standard Python logging and structlog
    for structured logging. Configuration is based on the application
    settings and environment.

    Args:
        settings: Application settings. If None, settings are loaded automatically.

    Example:
        >>> from src.config.settings import get_settings
        >>> configure_logging(get_settings())
    """
    if settings is None:
        from src.config.settings import get_settings

        settings = get_settings()

    _configure_standard_logging(settings)
    _configure_structlog(settings)

    # Log configuration completion
    logger = get_logger("system")
    logger.info(
        "Logging configured",
        log_format=settings.log_format,
        log_level=settings.log_level,
        environment=settings.environment,
    )


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    """Get a structured logger instance.

    Args:
        name: Logger name. If None, returns the root logger.
            Use predefined names from LOGGER_NAMES for consistency.

    Returns:
        Configured structlog logger instance.

    Example:
        >>> logger = get_logger("market_data")
        >>> logger.info("Market data received", symbol="CL=F", price=75.50)
        >>>
        >>> # With correlation ID
        >>> set_correlation_id("req-123")
        >>> logger.info("Processing request")  # Includes correlation ID
    """
    logger_name = name or "wti"
    return structlog.get_logger(logger_name)


class LoggingContext:
    """Context manager for temporary correlation ID setting.

    This context manager sets a correlation ID for the duration of the
    context and automatically clears it on exit.

    Example:
        >>> with LoggingContext("request-123"):
        ...     logger.info("Processing request")
        ...     # All logs within this block include correlation_id
        >>> # Correlation ID is cleared after the block
    """

    def __init__(self, correlation_id: str | None = None) -> None:
        """Initialize the logging context.

        Args:
            correlation_id: The correlation ID to set. If None, a new UUID is generated.
        """
        self.correlation_id = correlation_id or str(uuid.uuid4())
        self.token: Any = None

    def __enter__(self) -> "LoggingContext":
        """Enter the context and set correlation ID.

        Returns:
            The context instance.
        """
        self.token = correlation_id_var.set(self.correlation_id)
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Exit the context and clear correlation ID.

        Args:
            exc_type: Exception type if an exception occurred.
            exc_val: Exception value if an exception occurred.
            exc_tb: Exception traceback if an exception occurred.
        """
        correlation_id_var.reset(self.token)


def log_exception(
    logger: structlog.stdlib.BoundLogger,
    message: str,
    exc_info: bool = True,
    **kwargs: Any,
) -> None:
    """Log an exception with structured context.

    Args:
        logger: The logger to use.
        message: The log message.
        exc_info: Whether to include exception info. Defaults to True.
        **kwargs: Additional context fields.

    Example:
        >>> try:
        ...     risky_operation()
        ... except Exception as e:
        ...     log_exception(logger, "Operation failed", operation="risky")
    """
    logger.error(
        message,
        exc_info=exc_info,
        **kwargs,
    )
