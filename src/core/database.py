"""PostgreSQL database connection and session management.

This module provides async database connectivity using SQLAlchemy 2.0
with asyncpg driver. It includes connection pooling, health checks,
and proper session lifecycle management.
"""

from contextlib import asynccontextmanager
from typing import AsyncGenerator

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from src.config.settings import Settings, get_settings
from src.core.logging_config import get_logger

logger = get_logger("database")

# Global engine and session factory instances
_engine: AsyncEngine | None = None
_async_session_maker: async_sessionmaker[AsyncSession] | None = None


def create_engine(settings: Settings | None = None) -> AsyncEngine:
    """Create and configure the async database engine.

    Args:
        settings: Application settings. If None, settings are loaded automatically.

    Returns:
        Configured async SQLAlchemy engine.

    Raises:
        SQLAlchemyError: If engine creation fails.
    """
    if settings is None:
        settings = get_settings()

    db_config = settings.database

    # Connection pool arguments
    pool_kwargs = {
        "pool_size": db_config.pool_size,
        "max_overflow": db_config.max_overflow,
        "pool_timeout": db_config.pool_timeout,
        "pool_recycle": db_config.pool_recycle,
        "pool_pre_ping": True,  # Verify connections before using
        "echo": db_config.echo,
    }

    # Use NullPool for testing to avoid connection issues
    if settings.environment == "testing":
        pool_kwargs = {"poolclass": NullPool}

    engine = create_async_engine(
        db_config.async_url,
        future=True,
        **pool_kwargs,
    )

    logger.info(
        "Database engine created",
        pool_size=db_config.pool_size,
        max_overflow=db_config.max_overflow,
        echo=db_config.echo,
    )

    return engine


def get_engine() -> AsyncEngine:
    """Get the global database engine instance.

    Returns:
        The global engine instance.

    Raises:
        RuntimeError: If the engine has not been initialized.
    """
    if _engine is None:
        raise RuntimeError("Database engine not initialized. Call init_database() first.")
    return _engine


def create_session_maker(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """Create async session factory.

    Args:
        engine: The async engine to bind sessions to.

    Returns:
        Configured async session maker.
    """
    return async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
        autocommit=False,
    )


async def init_database(settings: Settings | None = None) -> None:
    """Initialize the database connection pool.

    This function must be called before any database operations.
    It creates the global engine and session factory.

    Args:
        settings: Application settings. If None, settings are loaded automatically.

    Example:
        >>> await init_database()
        >>> # Database is now ready for use
    """
    global _engine, _async_session_maker

    if _engine is not None:
        logger.warning("Database already initialized")
        return

    settings = settings or get_settings()
    _engine = create_engine(settings)
    _async_session_maker = create_session_maker(_engine)

    logger.info("Database initialized successfully")


async def close_database() -> None:
    """Close the database connection pool.

    This function should be called during application shutdown to
    properly release all database connections.

    Example:
        >>> await close_database()
        >>> # All connections are now closed
    """
    global _engine, _async_session_maker

    if _engine is None:
        logger.warning("Database not initialized, nothing to close")
        return

    try:
        await _engine.dispose()
        logger.info("Database connections disposed")
    except SQLAlchemyError as e:
        logger.error("Error disposing database engine", error=str(e))
        raise
    finally:
        _engine = None
        _async_session_maker = None


@asynccontextmanager
async def get_async_session() -> AsyncGenerator[AsyncSession, None]:
    """Get an async database session as a context manager.

    This context manager provides a database session with automatic
    commit/rollback handling and proper resource cleanup.

    Yields:
        AsyncSession: Database session instance.

    Raises:
        RuntimeError: If database not initialized.
        SQLAlchemyError: If database operations fail.

    Example:
        >>> async with get_async_session() as session:
        ...     result = await session.execute(select(MyModel))
        ...     # Session is automatically committed or rolled back
    """
    if _async_session_maker is None:
        raise RuntimeError("Database not initialized. Call init_database() first.")

    session = _async_session_maker()
    try:
        yield session
        await session.commit()
    except SQLAlchemyError as e:
        await session.rollback()
        logger.error("Database transaction failed", error=str(e))
        raise
    except Exception as e:
        await session.rollback()
        logger.error("Unexpected error in database session", error=str(e))
        raise
    finally:
        await session.close()


async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """Get an async database session for dependency injection.

    This generator is designed for use with FastAPI's dependency injection.
    It yields a session and handles cleanup automatically.

    Yields:
        AsyncSession: Database session instance.

    Example:
        >>> @app.get("/items")
        ... async def get_items(session: AsyncSession = Depends(get_db_session)):
        ...     return await session.execute(select(Item))
    """
    if _async_session_maker is None:
        raise RuntimeError("Database not initialized. Call init_database() first.")

    session = _async_session_maker()
    try:
        yield session
        await session.commit()
    except SQLAlchemyError as e:
        await session.rollback()
        logger.error("Database transaction failed", error=str(e))
        raise
    except Exception as e:
        await session.rollback()
        logger.error("Unexpected error in database session", error=str(e))
        raise
    finally:
        await session.close()


@retry(
    retry=retry_if_exception_type(SQLAlchemyError),
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=10),
    reraise=True,
)
async def check_database_health() -> dict[str, any]:
    """Check database connectivity and health.

    This function performs a simple query to verify database connectivity
    and returns health status information. It includes retry logic for
    transient failures.

    Returns:
        Dictionary containing health status information:
        - status: "healthy" or "unhealthy"
        - response_time_ms: Query response time in milliseconds
        - error: Error message if unhealthy

    Example:
        >>> health = await check_database_health()
        >>> if health["status"] == "healthy":
        ...     print(f"DB response time: {health['response_time_ms']}ms")
    """
    import time

    if _engine is None:
        return {
            "status": "unhealthy",
            "response_time_ms": 0,
            "error": "Database not initialized",
        }

    start_time = time.perf_counter()

    try:
        async with _engine.connect() as conn:
            result = await conn.execute(text("SELECT 1"))
            await result.scalar()

        response_time_ms = (time.perf_counter() - start_time) * 1000

        return {
            "status": "healthy",
            "response_time_ms": round(response_time_ms, 2),
        }

    except SQLAlchemyError as e:
        response_time_ms = (time.perf_counter() - start_time) * 1000
        logger.error("Database health check failed", error=str(e))
        return {
            "status": "unhealthy",
            "response_time_ms": round(response_time_ms, 2),
            "error": str(e),
        }


async def execute_with_retry(
    session: AsyncSession,
    statement: str,
    params: dict | None = None,
    max_retries: int = 3,
) -> any:
    """Execute a SQL statement with retry logic.

    Args:
        session: Database session.
        statement: SQL statement to execute.
        params: Query parameters.
        max_retries: Maximum number of retry attempts.

    Returns:
        Query result.

    Raises:
        SQLAlchemyError: If all retry attempts fail.
    """
    @retry(
        retry=retry_if_exception_type(SQLAlchemyError),
        stop=stop_after_attempt(max_retries),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        reraise=True,
    )
    async def _execute() -> any:
        result = await session.execute(text(statement), params)
        return result

    return await _execute()


class DatabaseManager:
    """Context manager for database lifecycle management.

    This class provides a convenient way to manage database initialization
    and cleanup using async context manager syntax.

    Example:
        >>> async with DatabaseManager() as db:
        ...     async with db.session() as session:
        ...         result = await session.execute(select(MyModel))
    """

    def __init__(self, settings: Settings | None = None) -> None:
        """Initialize the database manager.

        Args:
            settings: Application settings.
        """
        self.settings = settings or get_settings()
        self._engine: AsyncEngine | None = None

    async def __aenter__(self) -> "DatabaseManager":
        """Enter context and initialize database.

        Returns:
            DatabaseManager instance.
        """
        await init_database(self.settings)
        self._engine = get_engine()
        return self

    async def __aexit__(self, exc_type: any, exc_val: any, exc_tb: any) -> None:
        """Exit context and close database.

        Args:
            exc_type: Exception type if an error occurred.
            exc_val: Exception value if an error occurred.
            exc_tb: Exception traceback if an error occurred.
        """
        await close_database()

    @asynccontextmanager
    async def session(self) -> AsyncGenerator[AsyncSession, None]:
        """Get a database session.

        Yields:
            AsyncSession: Database session.
        """
        async with get_async_session() as session:
            yield session
