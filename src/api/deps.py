"""API dependencies for authentication and authorization.

Provides FastAPI dependencies for user authentication, including
API key validation and WebSocket authentication.
"""

from fastapi import Depends, HTTPException, Query, WebSocket, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from src.config.settings import get_settings
from src.core.logging_config import get_logger

logger = get_logger("api.deps")

# Security scheme for JWT/API key auth
security = HTTPBearer(auto_error=False)


async def get_current_active_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
    api_key: str | None = Query(None, alias="api_key"),
) -> dict:
    """Validate API key and return current user.
    
    Supports both Bearer token in Authorization header
    and api_key query parameter.
    
    Args:
        credentials: Authorization header credentials
        api_key: API key from query parameter
        
    Returns:
        User dictionary with permissions
        
    Raises:
        HTTPException: If authentication fails
    """
    settings = get_settings()
    
    # In development mode, allow requests without auth
    if not settings.is_production():
        return {
            "user_id": "dev_user",
            "permissions": ["read", "write", "admin"],
        }
    
    # Get API key from header or query param
    key = None
    if credentials:
        key = credentials.credentials
    elif api_key:
        key = api_key
    
    if not key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="API key required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    # Validate API key (in production, check against database)
    valid_keys = settings.api.api_keys if hasattr(settings.api, "api_keys") else []
    
    if key not in valid_keys:
        logger.warning("Invalid API key attempt")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    return {
        "user_id": f"api_user_{key[:8]}",
        "permissions": ["read", "write"],
    }


async def get_current_active_user_ws(
    websocket: WebSocket,
    api_key: str | None = Query(None),
) -> dict:
    """Validate API key for WebSocket connections.
    
    Args:
        websocket: WebSocket connection
        api_key: API key from query parameter
        
    Returns:
        User dictionary with permissions
        
    Raises:
        HTTPException: If authentication fails
    """
    settings = get_settings()
    
    # In development mode, allow connections without auth
    if not settings.is_production():
        return {
            "user_id": "dev_user",
            "permissions": ["read", "write", "admin"],
        }
    
    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="API key required",
        )
    
    # Validate API key
    valid_keys = settings.api.api_keys if hasattr(settings.api, "api_keys") else []
    
    if api_key not in valid_keys:
        logger.warning("Invalid WebSocket API key attempt")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key",
        )
    
    return {
        "user_id": f"ws_user_{api_key[:8]}",
        "permissions": ["read"],
    }


async def require_admin(
    user: dict = Depends(get_current_active_user),
) -> dict:
    """Require admin permissions.
    
    Args:
        user: Current user from authentication
        
    Returns:
        User dictionary
        
    Raises:
        HTTPException: If user lacks admin permissions
    """
    if "admin" not in user.get("permissions", []):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin permissions required",
        )
    return user
