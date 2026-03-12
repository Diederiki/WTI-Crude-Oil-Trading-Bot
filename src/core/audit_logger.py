"""Audit logging for compliance and security.

Provides tamper-evident audit logging for all critical operations
including trades, configuration changes, and administrative actions.
"""

import hashlib
import json
from datetime import datetime
from enum import Enum
from typing import Any

from sqlalchemy import Column, DateTime, Index, String, Text, create_engine
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import declarative_base, sessionmaker

from src.core.logging_config import get_logger

logger = get_logger("audit")

Base = declarative_base()


class AuditAction(str, Enum):
    """Audit action types."""
    
    # Trading actions
    ORDER_CREATED = "order_created"
    ORDER_FILLED = "order_filled"
    ORDER_CANCELLED = "order_cancelled"
    ORDER_REJECTED = "order_rejected"
    POSITION_OPENED = "position_opened"
    POSITION_CLOSED = "position_closed"
    
    # Risk actions
    KILL_SWITCH_ACTIVATED = "kill_switch_activated"
    KILL_SWITCH_RESET = "kill_switch_reset"
    RISK_LIMIT_BREACH = "risk_limit_breach"
    COOLDOWN_STARTED = "cooldown_started"
    
    # System actions
    CONFIG_CHANGED = "config_changed"
    SYSTEM_STARTED = "system_started"
    SYSTEM_STOPPED = "system_stopped"
    
    # Administrative actions
    USER_LOGIN = "user_login"
    USER_LOGOUT = "user_logout"
    PERMISSION_GRANTED = "permission_granted"
    PERMISSION_REVOKED = "permission_revoked"
    
    # Data actions
    DATA_EXPORTED = "data_exported"
    DATA_DELETED = "data_deleted"
    BACKUP_CREATED = "backup_created"
    BACKUP_RESTORED = "backup_restored"


class AuditLogEntry(Base):
    """Audit log database model."""
    
    __tablename__ = "audit_log"
    
    id = Column(String(36), primary_key=True)
    timestamp = Column(DateTime(timezone=True), nullable=False, index=True)
    action = Column(String(50), nullable=False, index=True)
    actor_type = Column(String(20), nullable=False)  # user, system, api
    actor_id = Column(String(100), nullable=False, index=True)
    resource_type = Column(String(50), nullable=False)
    resource_id = Column(String(100), nullable=True)
    details = Column(JSONB, nullable=True)
    ip_address = Column(String(45), nullable=True)
    user_agent = Column(String(500), nullable=True)
    session_id = Column(String(100), nullable=True)
    correlation_id = Column(String(36), nullable=True, index=True)
    previous_hash = Column(String(64), nullable=True)
    entry_hash = Column(String(64), nullable=False)
    
    # Indexes for common queries
    __table_args__ = (
        Index("ix_audit_timestamp_action", "timestamp", "action"),
        Index("ix_audit_actor_resource", "actor_type", "actor_id"),
    )


class AuditLogger:
    """Tamper-evident audit logger.
    
    Creates cryptographically linked audit entries to detect
    tampering with the audit trail.
    """
    
    def __init__(self, database_url: str | None = None):
        """Initialize audit logger.
        
        Args:
            database_url: Database connection URL
        """
        self._last_hash: str | None = None
        self._session = None
        
        if database_url:
            self._engine = create_engine(database_url)
            Base.metadata.create_all(self._engine)
            self._Session = sessionmaker(bind=self._engine)
        else:
            self._engine = None
            self._Session = None
    
    async def log(
        self,
        action: AuditAction,
        actor_type: str,
        actor_id: str,
        resource_type: str,
        resource_id: str | None = None,
        details: dict[str, Any] | None = None,
        ip_address: str | None = None,
        user_agent: str | None = None,
        session_id: str | None = None,
        correlation_id: str | None = None,
    ) -> str:
        """Create audit log entry.
        
        Args:
            action: Action type
            actor_type: Actor type (user, system, api)
            actor_id: Actor identifier
            resource_type: Resource type
            resource_id: Resource identifier
            details: Additional details
            ip_address: Client IP address
            user_agent: Client user agent
            session_id: Session identifier
            correlation_id: Correlation ID
            
        Returns:
            Entry ID
        """
        import uuid
        
        entry_id = str(uuid.uuid4())
        timestamp = datetime.utcnow()
        
        # Create entry data for hashing
        entry_data = {
            "id": entry_id,
            "timestamp": timestamp.isoformat(),
            "action": action.value,
            "actor_type": actor_type,
            "actor_id": actor_id,
            "resource_type": resource_type,
            "resource_id": resource_id,
            "details": details or {},
            "previous_hash": self._last_hash,
        }
        
        # Calculate hash
        entry_hash = self._calculate_hash(entry_data)
        
        # Create database entry
        if self._Session:
            session = self._Session()
            try:
                entry = AuditLogEntry(
                    id=entry_id,
                    timestamp=timestamp,
                    action=action.value,
                    actor_type=actor_type,
                    actor_id=actor_id,
                    resource_type=resource_type,
                    resource_id=resource_id,
                    details=details,
                    ip_address=ip_address,
                    user_agent=user_agent,
                    session_id=session_id,
                    correlation_id=correlation_id,
                    previous_hash=self._last_hash,
                    entry_hash=entry_hash,
                )
                session.add(entry)
                session.commit()
            except Exception as e:
                session.rollback()
                logger.error("Failed to write audit log", error=str(e))
                raise
            finally:
                session.close()
        
        # Update last hash
        self._last_hash = entry_hash
        
        # Also log to structured logger
        logger.info(
            "Audit log entry",
            entry_id=entry_id,
            action=action.value,
            actor=f"{actor_type}:{actor_id}",
            resource=f"{resource_type}:{resource_id}",
        )
        
        return entry_id
    
    def _calculate_hash(self, data: dict[str, Any]) -> str:
        """Calculate SHA-256 hash of entry data.
        
        Args:
            data: Entry data
            
        Returns:
            Hex hash string
        """
        # Serialize data deterministically
        serialized = json.dumps(data, sort_keys=True, default=str)
        return hashlib.sha256(serialized.encode()).hexdigest()
    
    async def verify_chain(self, start_id: str | None = None) -> tuple[bool, list[str]]:
        """Verify integrity of audit chain.
        
        Args:
            start_id: Entry ID to start from (None for all)
            
        Returns:
            Tuple of (valid, list of errors)
        """
        if not self._Session:
            return True, []
        
        errors = []
        session = self._Session()
        
        try:
            query = session.query(AuditLogEntry)
            if start_id:
                start_entry = session.query(AuditLogEntry).get(start_id)
                if start_entry:
                    query = query.filter(AuditLogEntry.timestamp >= start_entry.timestamp)
            
            entries = query.order_by(AuditLogEntry.timestamp).all()
            
            previous_hash: str | None = None
            
            for entry in entries:
                # Verify previous hash linkage
                if entry.previous_hash != previous_hash:
                    errors.append(
                        f"Hash mismatch at {entry.id}: "
                        f"expected {previous_hash}, got {entry.previous_hash}"
                    )
                
                # Recalculate and verify entry hash
                entry_data = {
                    "id": entry.id,
                    "timestamp": entry.timestamp.isoformat(),
                    "action": entry.action,
                    "actor_type": entry.actor_type,
                    "actor_id": entry.actor_id,
                    "resource_type": entry.resource_type,
                    "resource_id": entry.resource_id,
                    "details": entry.details or {},
                    "previous_hash": entry.previous_hash,
                }
                
                calculated_hash = self._calculate_hash(entry_data)
                if calculated_hash != entry.entry_hash:
                    errors.append(
                        f"Entry hash mismatch at {entry.id}: "
                        f"tampering detected"
                    )
                
                previous_hash = entry.entry_hash
            
            return len(errors) == 0, errors
            
        finally:
            session.close()
    
    async def query(
        self,
        action: AuditAction | None = None,
        actor_id: str | None = None,
        resource_type: str | None = None,
        resource_id: str | None = None,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """Query audit log entries.
        
        Args:
            action: Filter by action
            actor_id: Filter by actor
            resource_type: Filter by resource type
            resource_id: Filter by resource ID
            start_time: Filter by start time
            end_time: Filter by end time
            limit: Maximum results
            offset: Result offset
            
        Returns:
            List of audit entries
        """
        if not self._Session:
            return []
        
        session = self._Session()
        
        try:
            query = session.query(AuditLogEntry)
            
            if action:
                query = query.filter(AuditLogEntry.action == action.value)
            if actor_id:
                query = query.filter(AuditLogEntry.actor_id == actor_id)
            if resource_type:
                query = query.filter(AuditLogEntry.resource_type == resource_type)
            if resource_id:
                query = query.filter(AuditLogEntry.resource_id == resource_id)
            if start_time:
                query = query.filter(AuditLogEntry.timestamp >= start_time)
            if end_time:
                query = query.filter(AuditLogEntry.timestamp <= end_time)
            
            entries = (
                query.order_by(AuditLogEntry.timestamp.desc())
                .limit(limit)
                .offset(offset)
                .all()
            )
            
            return [
                {
                    "id": e.id,
                    "timestamp": e.timestamp.isoformat(),
                    "action": e.action,
                    "actor_type": e.actor_type,
                    "actor_id": e.actor_id,
                    "resource_type": e.resource_type,
                    "resource_id": e.resource_id,
                    "details": e.details,
                    "ip_address": e.ip_address,
                    "correlation_id": e.correlation_id,
                }
                for e in entries
            ]
            
        finally:
            session.close()


# Global audit logger instance
_audit_logger: AuditLogger | None = None


def init_audit_logger(database_url: str | None = None) -> AuditLogger:
    """Initialize global audit logger.
    
    Args:
        database_url: Database connection URL
        
    Returns:
        Audit logger instance
    """
    global _audit_logger
    _audit_logger = AuditLogger(database_url)
    return _audit_logger


def get_audit_logger() -> AuditLogger | None:
    """Get global audit logger instance.
    
    Returns:
        Audit logger or None if not initialized
    """
    return _audit_logger


async def audit_log(
    action: AuditAction,
    actor_type: str,
    actor_id: str,
    resource_type: str,
    resource_id: str | None = None,
    details: dict[str, Any] | None = None,
    **kwargs: Any,
) -> str | None:
    """Convenience function for audit logging.
    
    Args:
        action: Action type
        actor_type: Actor type
        actor_id: Actor identifier
        resource_type: Resource type
        resource_id: Resource identifier
        details: Additional details
        **kwargs: Additional fields
        
    Returns:
        Entry ID or None if logger not initialized
    """
    logger = get_audit_logger()
    if not logger:
        return None
    
    return await logger.log(
        action=action,
        actor_type=actor_type,
        actor_id=actor_id,
        resource_type=resource_type,
        resource_id=resource_id,
        details=details,
        **kwargs,
    )
