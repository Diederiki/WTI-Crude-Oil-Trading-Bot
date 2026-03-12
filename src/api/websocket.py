"""WebSocket API endpoints for real-time data streaming.

Provides WebSocket endpoints for subscribing to real-time market data,
signals, orders, positions, and system status updates.
"""

import json
from typing import Any

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect, status

from src.api.deps import get_current_active_user_ws
from src.core.logging_config import get_logger
from src.websocket.manager import WebSocketManager

logger = get_logger("api.websocket")

router = APIRouter(prefix="/ws", tags=["websocket"])

# Global WebSocket manager instance
_ws_manager: WebSocketManager | None = None


def set_websocket_manager(manager: WebSocketManager) -> None:
    """Set the global WebSocket manager instance.
    
    Args:
        manager: WebSocket manager instance
    """
    global _ws_manager
    _ws_manager = manager


def get_websocket_manager() -> WebSocketManager | None:
    """Get the global WebSocket manager instance.
    
    Returns:
        WebSocket manager instance or None
    """
    return _ws_manager


@router.websocket("/")
async def websocket_endpoint(websocket: WebSocket) -> None:
    """Main WebSocket endpoint for real-time data streaming.
    
    Clients can subscribe to different data types:
    - market_data: Real-time ticks and bars
    - signals: Trading signals
    - orders: Order updates and fills
    - positions: Position updates
    - system: System status
    - alerts: System alerts
    
    Message format for subscriptions:
    {
        "action": "subscribe",
        "type": "market_data"
    }
    
    Args:
        websocket: WebSocket connection
    """
    manager = get_websocket_manager()
    
    if not manager:
        await websocket.close(code=status.WS_1011_INTERNAL_ERROR)
        return
    
    client_id = f"ws_{id(websocket)}"
    await manager.connect(websocket, client_id)
    
    try:
        # Send welcome message
        await manager.send_to_client(websocket, {
            "type": "connected",
            "data": {
                "client_id": client_id,
                "message": "Connected to WTI Trading Bot WebSocket",
                "available_subscriptions": [
                    "market_data", "signals", "orders", "positions", "system", "alerts"
                ],
            },
        })
        
        # Handle incoming messages
        while True:
            try:
                message = await websocket.receive_text()
                data = json.loads(message)
                
                action = data.get("action")
                sub_type = data.get("type")
                
                if action == "subscribe" and sub_type:
                    manager.subscribe(websocket, sub_type)
                    await manager.send_to_client(websocket, {
                        "type": "subscribed",
                        "data": {"subscription_type": sub_type},
                    })
                    logger.debug("Client subscribed", client_id=client_id, type=sub_type)
                    
                elif action == "unsubscribe" and sub_type:
                    manager.unsubscribe(websocket, sub_type)
                    await manager.send_to_client(websocket, {
                        "type": "unsubscribed",
                        "data": {"subscription_type": sub_type},
                    })
                    logger.debug("Client unsubscribed", client_id=client_id, type=sub_type)
                    
                elif action == "ping":
                    await manager.send_to_client(websocket, {
                        "type": "pong",
                        "data": {"timestamp": __import__("datetime").datetime.utcnow().isoformat()},
                    })
                    
                else:
                    await manager.send_to_client(websocket, {
                        "type": "error",
                        "data": {"message": f"Unknown action: {action}"},
                    })
                    
            except json.JSONDecodeError:
                await manager.send_to_client(websocket, {
                    "type": "error",
                    "data": {"message": "Invalid JSON"},
                })
                
    except WebSocketDisconnect:
        logger.info("WebSocket client disconnected", client_id=client_id)
    except Exception as e:
        logger.error("WebSocket error", client_id=client_id, error=str(e))
    finally:
        manager.disconnect(websocket)


@router.websocket("/market-data")
async def market_data_websocket(websocket: WebSocket) -> None:
    """Dedicated WebSocket endpoint for market data only.
    
    Automatically subscribes to market_data stream on connection.
    
    Args:
        websocket: WebSocket connection
    """
    manager = get_websocket_manager()
    
    if not manager:
        await websocket.close(code=status.WS_1011_INTERNAL_ERROR)
        return
    
    client_id = f"md_{id(websocket)}"
    await manager.connect(websocket, client_id)
    manager.subscribe(websocket, "market_data")
    
    try:
        await manager.send_to_client(websocket, {
            "type": "connected",
            "data": {"message": "Connected to market data stream"},
        })
        
        # Keep connection alive, handle ping/pong
        while True:
            message = await websocket.receive_text()
            data = json.loads(message)
            
            if data.get("action") == "ping":
                await manager.send_to_client(websocket, {"type": "pong"})
                
    except WebSocketDisconnect:
        logger.info("Market data WebSocket disconnected", client_id=client_id)
    except Exception as e:
        logger.error("Market data WebSocket error", client_id=client_id, error=str(e))
    finally:
        manager.disconnect(websocket)


@router.websocket("/signals")
async def signals_websocket(websocket: WebSocket) -> None:
    """Dedicated WebSocket endpoint for trading signals only.
    
    Automatically subscribes to signals stream on connection.
    
    Args:
        websocket: WebSocket connection
    """
    manager = get_websocket_manager()
    
    if not manager:
        await websocket.close(code=status.WS_1011_INTERNAL_ERROR)
        return
    
    client_id = f"sig_{id(websocket)}"
    await manager.connect(websocket, client_id)
    manager.subscribe(websocket, "signals")
    
    try:
        await manager.send_to_client(websocket, {
            "type": "connected",
            "data": {"message": "Connected to signals stream"},
        })
        
        while True:
            message = await websocket.receive_text()
            data = json.loads(message)
            
            if data.get("action") == "ping":
                await manager.send_to_client(websocket, {"type": "pong"})
                
    except WebSocketDisconnect:
        logger.info("Signals WebSocket disconnected", client_id=client_id)
    except Exception as e:
        logger.error("Signals WebSocket error", client_id=client_id, error=str(e))
    finally:
        manager.disconnect(websocket)


@router.websocket("/orders")
async def orders_websocket(websocket: WebSocket) -> None:
    """Dedicated WebSocket endpoint for order updates only.
    
    Automatically subscribes to orders stream on connection.
    
    Args:
        websocket: WebSocket connection
    """
    manager = get_websocket_manager()
    
    if not manager:
        await websocket.close(code=status.WS_1011_INTERNAL_ERROR)
        return
    
    client_id = f"ord_{id(websocket)}"
    await manager.connect(websocket, client_id)
    manager.subscribe(websocket, "orders")
    
    try:
        await manager.send_to_client(websocket, {
            "type": "connected",
            "data": {"message": "Connected to orders stream"},
        })
        
        while True:
            message = await websocket.receive_text()
            data = json.loads(message)
            
            if data.get("action") == "ping":
                await manager.send_to_client(websocket, {"type": "pong"})
                
    except WebSocketDisconnect:
        logger.info("Orders WebSocket disconnected", client_id=client_id)
    except Exception as e:
        logger.error("Orders WebSocket error", client_id=client_id, error=str(e))
    finally:
        manager.disconnect(websocket)


@router.websocket("/positions")
async def positions_websocket(websocket: WebSocket) -> None:
    """Dedicated WebSocket endpoint for position updates only.
    
    Automatically subscribes to positions stream on connection.
    
    Args:
        websocket: WebSocket connection
    """
    manager = get_websocket_manager()
    
    if not manager:
        await websocket.close(code=status.WS_1011_INTERNAL_ERROR)
        return
    
    client_id = f"pos_{id(websocket)}"
    await manager.connect(websocket, client_id)
    manager.subscribe(websocket, "positions")
    
    try:
        await manager.send_to_client(websocket, {
            "type": "connected",
            "data": {"message": "Connected to positions stream"},
        })
        
        while True:
            message = await websocket.receive_text()
            data = json.loads(message)
            
            if data.get("action") == "ping":
                await manager.send_to_client(websocket, {"type": "pong"})
                
    except WebSocketDisconnect:
        logger.info("Positions WebSocket disconnected", client_id=client_id)
    except Exception as e:
        logger.error("Positions WebSocket error", client_id=client_id, error=str(e))
    finally:
        manager.disconnect(websocket)


@router.get("/stats", response_model=dict[str, Any])
async def get_websocket_stats(
    current_user: dict = Depends(get_current_active_user_ws),
) -> dict[str, Any]:
    """Get WebSocket connection statistics.
    
    Returns:
        WebSocket statistics dictionary
    """
    manager = get_websocket_manager()
    
    if not manager:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="WebSocket manager not initialized",
        )
    
    return manager.get_stats()
