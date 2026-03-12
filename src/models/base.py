"""SQLAlchemy base models and mixins.

This module provides the foundation for all database models including:
- Declarative base class
- Timestamp mixin for created_at/updated_at columns
- UUID primary key mixin
- Async-compatible column types
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, func
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Base class for all SQLAlchemy models.

    This class provides the foundation for declarative model definitions.
    All models should inherit from this base class.

    Example:
        >>> class MyModel(Base):
        ...     __tablename__ = "my_table"
        ...     id: Mapped[int] = mapped_column(primary_key=True)
    """

    # Enable automatic table name generation from class name
    # Override in subclasses with __tablename__ if needed
    def __init_subclass__(cls, **kwargs: Any) -> None:
        """Set default tablename if not specified."""
        if not hasattr(cls, "__tablename__"):
            # Convert CamelCase to snake_case
            name = cls.__name__
            snake_case = "".join(
                ["_" + c.lower() if c.isupper() else c for c in name]
            ).lstrip("_")
            cls.__tablename__ = f"{snake_case}s"
        super().__init_subclass__(**kwargs)


class TimestampMixin:
    """Mixin adding created_at and updated_at timestamp columns.

    This mixin automatically tracks when records are created and modified.
    Use it by including it in the inheritance chain of your models.

    Example:
        >>> class MyModel(Base, TimestampMixin):
        ...     __tablename__ = "my_table"
        ...     id: Mapped[int] = mapped_column(primary_key=True)
        ...     # created_at and updated_at are automatically added
    """

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        doc="Timestamp when the record was created",
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
        doc="Timestamp when the record was last updated",
    )


class UUIDMixin:
    """Mixin adding UUID primary key column.

    This mixin provides a UUID-based primary key for models that need
    globally unique identifiers.

    Example:
        >>> class MyModel(Base, UUIDMixin):
        ...     __tablename__ = "my_table"
        ...     name: Mapped[str] = mapped_column()
        ...     # id (UUID) is automatically added as primary key
    """

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        nullable=False,
        doc="Unique identifier (UUID v4)",
    )


class TimestampUUIDMixin(TimestampMixin, UUIDMixin):
    """Combined mixin with both UUID primary key and timestamps.

    This is a convenience mixin that combines both UUIDMixin and
    TimestampMixin for models that need both features.

    Example:
        >>> class MyModel(Base, TimestampUUIDMixin):
        ...     __tablename__ = "my_table"
        ...     name: Mapped[str] = mapped_column()
        ...     # id, created_at, updated_at are automatically added
    """

    pass


class SoftDeleteMixin:
    """Mixin adding soft delete functionality.

    This mixin adds a deleted_at column for soft deletion instead of
    hard deletion. Records with a non-null deleted_at are considered deleted.

    Example:
        >>> class MyModel(Base, TimestampMixin, SoftDeleteMixin):
        ...     __tablename__ = "my_table"
        ...     name: Mapped[str] = mapped_column()
        ...     # deleted_at is automatically added
    """

    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        default=None,
        doc="Timestamp when the record was soft deleted",
    )

    @property
    def is_deleted(self) -> bool:
        """Check if the record has been soft deleted.

        Returns:
            True if the record is deleted, False otherwise.
        """
        return self.deleted_at is not None

    def soft_delete(self) -> None:
        """Mark the record as deleted without removing from database."""
        self.deleted_at = datetime.now()

    def restore(self) -> None:
        """Restore a soft-deleted record."""
        self.deleted_at = None
