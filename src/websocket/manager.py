"""WebSocket manager for connection handling and broadcasting.

Manages WebSocket connections, handles subscriptions, and broadcasts
real-time updates to connected clients.
"""

import asyncio
import json
from collections import defaultdict
from typing import Any

from fastapi import WebSocket

from src.core.logging_config import get_logger

logger = get_logger("websocket")


class WebSocketManager:
    """Manages WebSocket connections and broadcasting.
    
    Handles client connections, subscription management, and broadcasting
    messages to subscribed clients.
    
    Attributes:
        _connections: Set of active WebSocket connections
        _subscriptions: Mapping of subscription types to connection sets
        _connection_info: Metadata about each connection
    """
    
    def __init__(self):
        """Initialize WebSocket manager."""
        self._connections: set[WebSocket] = set()
        self._subscriptions: dict[str, set[WebSocket]] = defaultdict(set)
        self._connection_info: dict[WebSocket, dict[str, Any]] = {}
        
        logger.info("WebSocket manager initialized")
    
    async def connect(self, websocket: WebSocket, client_id: str | None = None) -> None:
        """Accept and register a new WebSocket connection.
        
        Args:
            websocket: WebSocket connection
            client_id: Optional client identifier
        """
        await websocket.accept()
        
        self._connections.add(websocket)
        self._connection_info[websocket] = {
            "client_id": client_id or f"anon_{id(websocket)}",
            "connected_at": asyncio.get_event_loop().time(),
            "subscriptions": set(),
        }
        
        logger.info(
            "WebSocket client connected",
            client_id=self._connection_info[websocket]["client_id"],
            total_connections=len(self._connections),
        )
    
    def disconnect(self, websocket: WebSocket) -> None:
        """Remove a WebSocket connection.
        
        Args:
            websocket: WebSocket connection to remove
        """
        client_info = self._connection_info.pop(websocket, {})
        
        # Remove from all subscriptions
        for subscription_type in list(self._subscriptions.keys()):
            self._subscriptions[subscription_type].discard(websocket)
        
        self._connections.discard(websocket)
        
        logger.info(
            "WebSocket client disconnected",
            client_id=client_info.get("client_id", "unknown"),
            total_connections=len(self._connections),
        )
    
    def subscribe(self, websocket: WebSocket, subscription_type: str) -> None:
        """Subscribe a connection to a message type.
        
        Args:
            websocket: WebSocket connection
            subscription_type: Type of messages to receive
        """
        self._subscriptions[subscription_type].add(websocket)
        
        if websocket in self._connection_info:
            self._connection_info[websocket]["subscriptions"].add(subscription_type)
        
        logger.debug(
            "Client subscribed",
            subscription_type=subscription_type,
            client_id=self._connection_info.get(websocket, {}).get("client_id"),
        )
    
    def unsubscribe(self, websocket: WebSocket, subscription_type: str) -> None:
        """Unsubscribe a connection from a message type.
        
        Args:
            websocket: WebSocket connection
            subscription_type: Type of messages to stop receiving
        """
        self._subscriptions[subscription_type].discard(websocket)
        
        if websocket in self._connection_info:
            self._connection_info[websocket]["subscriptions"].discard(subscription_type)
        
        logger.debug(
            "Client unsubscribed",
            subscription_type=subscription_type,
            client_id=self._connection_info.get(websocket, {}).get("client_id"),
        )
    
    async def broadcast(
        self,
        message: dict[str, Any],
        subscription_type: str | None = None,
    ) -> None:
        """Broadcast a message to all or subscribed clients.
        
        Args:
            message: Message to broadcast
            subscription_type: Optional subscription type filter
        """
        if subscription_type:
            targets = self._subscriptions.get(subscription_type, set())
        else:
            targets = self._connections
        
        if not targets:
            return
        
        message_json = json.dumps(message, default=str)
        
        # Send to all targets concurrently
        tasks = []
        for connection in targets:
            tasks.append(self._send_safe(connection, message_json))
        
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
    
    async def send_to_client(
        self,
        websocket: WebSocket,
        message: dict[str, Any],
    ) -> bool:
        """Send a message to a specific client.
        
        Args:
            websocket: Target WebSocket connection
            message: Message to send
            
        Returns:
            True if sent successfully
        """
        try:
            await websocket.send_json(message)
            return True
        except Exception as e:
            logger.error("Failed to send to client", error=str(e))
            return False
    
    async def _send_safe(self, websocket: WebSocket, message_json: str) -> None:
        """Safely send a message to a client.
        
        Args:
            websocket: Target WebSocket connection
            message_json: JSON message string
        """
        try:
            await websocket.send_text(message_json)
        except Exception as e:
            logger.debug("Failed to send to client, removing", error=str(e))
            self.disconnect(websocket)
    
    def get_connection_count(self) -> int:
        """Get number of active connections.
        
        Returns:
            Connection count
        """
        return len(self._connections)
    
    def get_subscription_stats(self) -> dict[str, int]:
        """Get subscription statistics.
        
        Returns:
            Dictionary of subscription type -> count
        """
        return {
            sub_type: len(connections)
            for sub_type, connections in self._subscriptions.items()
        }
    
    def get_stats(self) -> dict[str, Any]:
        """Get manager statistics.
        
        Returns:
            Statistics dictionary
        """
        return {
            "total_connections": len(self._connections),
            "subscriptions": self.get_subscription_stats(),
            "clients": [
                {
                    "client_id": info.get("client_id"),
                    "subscriptions": list(info.get("subscriptions", [])),
                }
                for info in self._connection_info.values()
            ],
        }