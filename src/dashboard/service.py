"""Dashboard service for aggregating system status.

Provides comprehensive system overview by aggregating data from all
components: feed manager, strategy engine, execution engine, risk manager,
event engine, and WebSocket manager.
"""

from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

from src.core.logging_config import get_logger

logger = get_logger("dashboard")


class DashboardService:
    """Service for aggregating dashboard data from all components.
    
    Provides unified access to system status, market data, signals,
    orders, positions, and risk metrics for dashboard display.
    
    Attributes:
        feed_manager: Market data feed manager
        strategy_engine: Strategy engine for signal data
        execution_engine: Execution engine for order/position data
        risk_manager: Risk manager for risk metrics
        event_engine: Event engine for calendar data
        ws_manager: WebSocket manager for connection stats
    """
    
    def __init__(
        self,
        feed_manager=None,
        strategy_engine=None,
        execution_engine=None,
        risk_manager=None,
        event_engine=None,
        ws_manager=None,
    ):
        """Initialize dashboard service.
        
        Args:
            feed_manager: Feed manager instance
            strategy_engine: Strategy engine instance
            execution_engine: Execution engine instance
            risk_manager: Risk manager instance
            event_engine: Event engine instance
            ws_manager: WebSocket manager instance
        """
        self.feed_manager = feed_manager
        self.strategy_engine = strategy_engine
        self.execution_engine = execution_engine
        self.risk_manager = risk_manager
        self.event_engine = event_engine
        self.ws_manager = ws_manager
        
        logger.info("Dashboard service initialized")
    
    def get_full_status(self) -> dict[str, Any]:
        """Get complete system status for dashboard.
        
        Returns:
            Dictionary with all system status information
        """
        return {
            "timestamp": datetime.utcnow().isoformat(),
            "system": self._get_system_status(),
            "market_data": self._get_market_data_status(),
            "strategy": self._get_strategy_status(),
            "execution": self._get_execution_status(),
            "risk": self._get_risk_status(),
            "events": self._get_event_status(),
            "websocket": self._get_websocket_status(),
        }
    
    def get_symbol_overview(self, symbol: str) -> dict[str, Any]:
        """Get overview for a specific symbol.
        
        Args:
            symbol: Trading symbol
            
        Returns:
            Symbol overview dictionary
        """
        overview = {
            "symbol": symbol.upper(),
            "timestamp": datetime.utcnow().isoformat(),
        }
        
        # Price data from feed manager
        if self.feed_manager:
            price_data = self.feed_manager.get_last_price(symbol)
            if price_data:
                overview["price"] = {
                    "bid": price_data.get("bid"),
                    "ask": price_data.get("ask"),
                    "last": price_data.get("last"),
                    "spread": price_data.get("spread"),
                    "timestamp": price_data.get("timestamp"),
                }
        
        # Position data
        if self.execution_engine and self.execution_engine.broker:
            position = self.execution_engine.broker.get_position(symbol)
            if position:
                overview["position"] = {
                    "side": position.side.value,
                    "quantity": position.quantity,
                    "entry_price": str(position.entry_price),
                    "current_price": str(position.current_price) if position.current_price else None,
                    "unrealized_pnl": str(position.unrealized_pnl),
                    "pnl_percentage": position.pnl_percentage,
                    "is_open": position.is_open,
                }
        
        # Active orders
        if self.execution_engine:
            orders = self.execution_engine.get_active_orders(symbol)
            overview["active_orders"] = [
                {
                    "order_id": o.order_id,
                    "side": o.side.value,
                    "status": o.status.value,
                    "quantity": o.quantity,
                    "filled_quantity": o.filled_quantity,
                    "fill_percentage": o.fill_percentage,
                }
                for o in orders
            ]
        
        return overview
    
    def get_performance_summary(self) -> dict[str, Any]:
        """Get trading performance summary.
        
        Returns:
            Performance metrics dictionary
        """
        summary = {
            "timestamp": datetime.utcnow().isoformat(),
            "period": "all_time",
        }
        
        if self.execution_engine and self.execution_engine.broker:
            broker = self.execution_engine.broker
            
            # Account info
            summary["account"] = {
                "balance": str(broker.get_balance()),
                "initial_balance": str(broker.initial_balance),
                "total_pnl": str(broker.get_total_pnl()),
                "total_pnl_pct": float(
                    (broker.get_total_pnl() / broker.initial_balance) * 100
                ) if broker.initial_balance > 0 else 0.0,
            }
            
            # Position summary
            positions = broker.get_all_positions()
            open_positions = [p for p in positions if p.is_open]
            closed_positions = [p for p in positions if not p.is_open]
            
            summary["positions"] = {
                "total": len(positions),
                "open": len(open_positions),
                "closed": len(closed_positions),
                "open_pnl": str(sum(p.unrealized_pnl for p in open_positions)),
                "realized_pnl": str(sum(p.realized_pnl for p in closed_positions)),
            }
            
            # Order statistics
            orders = broker.get_all_orders()
            filled_orders = [o for o in orders if o.status.value == "filled"]
            cancelled_orders = [o for o in orders if o.status.value == "cancelled"]
            
            summary["orders"] = {
                "total": len(orders),
                "filled": len(filled_orders),
                "cancelled": len(cancelled_orders),
                "fill_rate": len(filled_orders) / len(orders) * 100 if orders else 0.0,
            }
        
        return summary
    
    def get_recent_signals(self, limit: int = 20) -> list[dict[str, Any]]:
        """Get recent trading signals.
        
        Args:
            limit: Maximum number of signals to return
            
        Returns:
            List of signal dictionaries
        """
        if not self.strategy_engine:
            return []
        
        signals = self.strategy_engine.get_recent_signals(limit)
        return [
            {
                "signal_id": s.signal_id,
                "timestamp": s.timestamp.isoformat(),
                "symbol": s.symbol,
                "signal_type": s.signal_type.value,
                "direction": s.direction,
                "trigger_price": s.trigger_price,
                "confidence": s.confidence,
                "setup_description": s.setup_description,
                "risk_reward_ratio": s.risk_reward_ratio,
            }
            for s in signals
        ]
    
    def get_recent_orders(self, limit: int = 20) -> list[dict[str, Any]]:
        """Get recent orders.
        
        Args:
            limit: Maximum number of orders to return
            
        Returns:
            List of order dictionaries
        """
        if not self.execution_engine or not self.execution_engine.broker:
            return []
        
        orders = self.execution_engine.broker.get_all_orders()
        orders = sorted(orders, key=lambda o: o.created_at, reverse=True)[:limit]
        
        return [
            {
                "order_id": o.order_id,
                "symbol": o.symbol,
                "side": o.side.value,
                "status": o.status.value,
                "quantity": o.quantity,
                "filled_quantity": o.filled_quantity,
                "average_fill_price": str(o.average_fill_price) if o.average_fill_price else None,
                "fill_percentage": o.fill_percentage,
                "created_at": o.created_at.isoformat(),
            }
            for o in orders
        ]
    
    def get_recent_fills(self, limit: int = 20) -> list[dict[str, Any]]:
        """Get recent order fills.
        
        Args:
            limit: Maximum number of fills to return
            
        Returns:
            List of fill dictionaries
        """
        if not self.execution_engine or not self.execution_engine.broker:
            return []
        
        fills = self.execution_engine.broker.get_recent_fills(limit)
        return [
            {
                "fill_id": f["fill_id"],
                "order_id": f["order_id"],
                "symbol": f["symbol"],
                "quantity": f["quantity"],
                "price": str(f["price"]),
                "commission": str(f["commission"]),
                "timestamp": f["timestamp"].isoformat(),
            }
            for f in fills
        ]
    
    def get_risk_metrics(self) -> dict[str, Any]:
        """Get current risk metrics.
        
        Returns:
            Risk metrics dictionary
        """
        if not self.risk_manager:
            return {"status": "risk_manager_not_initialized"}
        
        metrics = self.risk_manager.get_metrics()
        limits = self.risk_manager.limits
        
        return {
            "timestamp": datetime.utcnow().isoformat(),
            "kill_switch_active": self.risk_manager.kill_switch_active,
            "daily_stats": {
                "pnl": str(metrics.daily_pnl),
                "trades": metrics.daily_trades,
                "volume": str(metrics.daily_volume),
            },
            "drawdown": {
                "current_pct": float(metrics.drawdown_pct),
                "max_pct": float(metrics.max_drawdown_pct),
            },
            "limits": {
                "max_position_size": limits.max_position_size,
                "max_position_pct": float(limits.max_position_pct),
                "max_open_positions": limits.max_open_positions,
                "max_daily_loss": str(limits.max_daily_loss),
                "max_drawdown_pct": float(limits.max_drawdown_pct),
                "per_trade_risk": float(limits.per_trade_risk),
                "max_trades_per_day": limits.max_trades_per_day,
            },
            "cooldown": {
                "in_cooldown": metrics.in_cooldown,
                "cooldown_until": metrics.cooldown_until.isoformat() if metrics.cooldown_until else None,
            },
        }
    
    def get_upcoming_events(self, hours: int = 24) -> list[dict[str, Any]]:
        """Get upcoming economic events.
        
        Args:
            hours: Number of hours to look ahead
            
        Returns:
            List of upcoming event dictionaries
        """
        if not self.event_engine:
            return []
        
        events = self.event_engine.get_upcoming_events(hours=hours)
        return [
            {
                "event_id": e.event_id,
                "name": e.name,
                "event_type": e.event_type.value,
                "scheduled_time": e.scheduled_time.isoformat(),
                "symbol": e.symbol,
                "impact": e.impact.value,
                "description": e.description,
                "minutes_until": (e.scheduled_time - datetime.utcnow()).total_seconds() / 60,
            }
            for e in events
        ]
    
    def _get_system_status(self) -> dict[str, Any]:
        """Get system component status.
        
        Returns:
            System status dictionary
        """
        import psutil
        
        return {
            "cpu_percent": psutil.cpu_percent(interval=0.1),
            "memory_percent": psutil.virtual_memory().percent,
            "disk_percent": psutil.disk_usage("/").percent,
            "components": {
                "feed_manager": "running" if self.feed_manager else "not_initialized",
                "strategy_engine": "running" if self.strategy_engine else "not_initialized",
                "execution_engine": "running" if self.execution_engine else "not_initialized",
                "risk_manager": "running" if self.risk_manager else "not_initialized",
                "event_engine": "running" if self.event_engine else "not_initialized",
                "websocket": "running" if self.ws_manager else "not_initialized",
            },
        }
    
    def _get_market_data_status(self) -> dict[str, Any]:
        """Get market data component status.
        
        Returns:
            Market data status dictionary
        """
        if not self.feed_manager:
            return {"status": "not_initialized"}
        
        feeds = self.feed_manager.get_feed_status()
        return {
            "status": "running",
            "feeds": feeds,
            "symbols_tracked": len(self.feed_manager._last_prices),
        }
    
    def _get_strategy_status(self) -> dict[str, Any]:
        """Get strategy engine status.
        
        Returns:
            Strategy status dictionary
        """
        if not self.strategy_engine:
            return {"status": "not_initialized"}
        
        return {
            "status": "running" if self.strategy_engine._running else "stopped",
            "signals_generated": self.strategy_engine.get_signal_count(),
            "recent_signals": len(self.strategy_engine.get_recent_signals(10)),
        }
    
    def _get_execution_status(self) -> dict[str, Any]:
        """Get execution engine status.
        
        Returns:
            Execution status dictionary
        """
        if not self.execution_engine:
            return {"status": "not_initialized"}
        
        broker = self.execution_engine.broker
        return {
            "status": "running" if self.execution_engine._running else "stopped",
            "broker_type": broker.__class__.__name__ if broker else "none",
            "active_orders": len(self.execution_engine.get_active_orders()),
            "open_positions": len(broker.get_open_positions()) if broker else 0,
        }
    
    def _get_risk_status(self) -> dict[str, Any]:
        """Get risk manager status.
        
        Returns:
            Risk status dictionary
        """
        if not self.risk_manager:
            return {"status": "not_initialized"}
        
        metrics = self.risk_manager.get_metrics()
        return {
            "status": "active",
            "kill_switch": "ACTIVE" if self.risk_manager.kill_switch_active else "inactive",
            "daily_pnl": str(metrics.daily_pnl),
            "drawdown_pct": float(metrics.drawdown_pct),
            "in_cooldown": metrics.in_cooldown,
        }
    
    def _get_event_status(self) -> dict[str, Any]:
        """Get event engine status.
        
        Returns:
            Event status dictionary
        """
        if not self.event_engine:
            return {"status": "not_initialized"}
        
        upcoming = self.event_engine.get_upcoming_events(hours=24)
        return {
            "status": "running" if self.event_engine._running else "stopped",
            "events_next_24h": len(upcoming),
            "high_impact_events": len([e for e in upcoming if e.impact.value == "high"]),
        }
    
    def _get_websocket_status(self) -> dict[str, Any]:
        """Get WebSocket manager status.
        
        Returns:
            WebSocket status dictionary
        """
        if not self.ws_manager:
            return {"status": "not_initialized"}
        
        stats = self.ws_manager.get_stats()
        return {
            "status": "running",
            "connections": stats["total_connections"],
            "subscriptions": stats["subscriptions"],
        }


# Global dashboard service instance
_dashboard_service: DashboardService | None = None


def set_dashboard_service(service: DashboardService) -> None:
    """Set the global dashboard service instance.
    
    Args:
        service: Dashboard service instance
    """
    global _dashboard_service
    _dashboard_service = service


def get_dashboard_service() -> DashboardService | None:
    """Get the global dashboard service instance.
    
    Returns:
        Dashboard service instance or None
    """
    return _dashboard_service
