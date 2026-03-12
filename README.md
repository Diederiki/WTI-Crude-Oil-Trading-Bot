# WTI Trading Bot

A production-grade, event-driven trading bot for WTI crude oil futures with real-time market data processing, signal generation, and order execution.

## Features

- **Event-Driven Architecture**: Real-time processing of market data with minimal latency
- **Risk Management**: Comprehensive risk controls including position limits, daily loss limits, and emergency kill switch
- **Market Data Processing**: Tick aggregation, OHLCV bar generation, and feed anomaly detection
- **Signal Generation**: Pluggable strategy framework for trading signals
- **Order Management**: Full order lifecycle management with fill tracking
- **Position Tracking**: Real-time P&L calculation and position monitoring
- **Health Monitoring**: Comprehensive health checks and observability
- **Production Ready**: Structured logging, metrics, graceful degradation

## Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              WTI Trading Bot                                │
├─────────────────────────────────────────────────────────────────────────────┤
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐     │
│  │ Market Data  │  │   Signals    │  │    Orders    │  │    Risk      │     │
│  │   Feeds      │──│  Strategies  │──│  Execution   │──│ Management   │     │
│  └──────────────┘  └──────────────┘  └──────────────┘  └──────────────┘     │
│         │                 │                 │                 │             │
│         └─────────────────┴─────────────────┴─────────────────┘             │
│                                    │                                        │
│                         ┌──────────┴──────────┐                             │
│                         │   Event Bus (Redis) │                             │
│                         └──────────┬──────────┘                             │
│                                    │                                        │
│  ┌─────────────────────────────────┼─────────────────────────────────┐      │
│  │                                 │                                 │      │
│  │  ┌──────────────┐    ┌─────────┴─────────┐    ┌──────────────┐    │      │
│  │  │ PostgreSQL   │    │     FastAPI       │    │   Redis      │    │      │
│  │  │  (Data)      │    │     (REST API)    │    │  (Cache)     │    │      │
│  │  └──────────────┘    └───────────────────┘    └──────────────┘    │      │
│  │                                                                   │      │
│  │  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐         │      │
│  │  │   Health     │    │   Metrics    │    │    Logs      │         │      │
│  │  │   Monitor    │    │ (Prometheus) │    │ (Structured) │         │      │
│  │  └──────────────┘    └──────────────┘    └──────────────┘         │      │
│  │                                                                   │      │
│  └────────────────────────────────────────────────────────────────── ┘      │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Project Structure

```
wti-trading-bot/
├── docker-compose.yml          # Docker orchestration
├── pyproject.toml              # Python dependencies and config
├── .env.example                # Environment variables template
├── README.md                   # This file
├── src/                        # Source code
│   ├── __init__.py
│   ├── main.py                 # FastAPI application entry point
│   ├── config/                 # Configuration management
│   │   ├── __init__.py
│   │   └── settings.py         # Pydantic Settings
│   ├── core/                   # Core infrastructure
│   │   ├── __init__.py
│   │   ├── logging_config.py   # Structured logging
│   │   ├── database.py         # PostgreSQL connection
│   │   ├── redis_client.py     # Redis client
│   │   ├── circuit_breaker.py  # Fault tolerance
│   │   ├── rate_limiter.py     # Rate limiting
│   │   ├── retry.py            # Retry with backoff
│   │   ├── audit_logger.py     # Audit logging
│   │   ├── security_middleware.py  # Security middleware
│   │   ├── data_retention.py   # Data retention
│   │   └── secrets.py          # Secrets management
│   ├── models/                 # Database models
│   │   ├── __init__.py
│   │   └── base.py             # SQLAlchemy base
│   ├── api/                    # API endpoints
│   │   ├── __init__.py
│   │   ├── router.py           # Router aggregation
│   │   ├── health.py           # Health checks
│   │   ├── system.py           # System endpoints
│   │   ├── market_data.py      # Market data endpoints
│   │   └── signals.py          # Signal endpoints
│   ├── market_data/            # Market data ingestion
│   │   ├── __init__.py
│   │   ├── models/
│   │   │   ├── __init__.py
│   │   │   └── events.py       # Tick, Bar, FeedStatus models
│   │   ├── adapters/
│   │   │   ├── __init__.py
│   │   │   ├── base.py         # FeedAdapter interface
│   │   │   └── simulated.py    # Simulated feed for testing
│   │   ├── feed_manager.py     # Multi-feed orchestration
│   │   ├── aggregator.py       # Tick-to-bar aggregation
│   │   ├── anomaly_detector.py # Feed quality monitoring
│   │   └── heartbeat.py        # Feed health monitoring
│   ├── event_bus/              # Internal pub/sub
│   │   ├── __init__.py
│   │   ├── events.py           # Event definitions
│   │   └── bus.py              # Event bus implementation
│   ├── strategy/               # Strategy engine
│   │   ├── __init__.py
│   │   ├── models/
│   │   │   ├── __init__.py
│   │   │   └── signal.py       # Signal model with scoring
│   │   ├── detectors/
│   │   │   ├── __init__.py
│   │   │   ├── liquidity_sweep.py  # Sweep detector
│   │   │   ├── breakout.py     # Breakout detector
│   │   │   ├── correlation.py  # Correlation detector
│   │   │   └── fake_spike_filter.py  # Fake spike filter
│   │   └── engine.py           # Strategy orchestration
│   ├── execution/              # Order execution
│   │   ├── __init__.py
│   │   ├── models/
│   │   │   ├── __init__.py
│   │   │   ├── order.py        # Order model
│   │   │   └── position.py     # Position model
│   │   ├── brokers/
│   │   │   ├── __init__.py
│   │   │   ├── base.py         # Broker interface
│   │   │   └── paper.py        # Paper broker
│   │   └── engine.py           # Execution engine
│   ├── risk/                   # Risk management
│   │   ├── __init__.py
│   │   ├── models.py           # Risk models
│   │   └── manager.py          # Risk manager
│   ├── events/                 # Event/news engine
│   │   ├── __init__.py
│   │   ├── models.py           # Event models
│   │   ├── calendar.py         # Event calendar
│   │   └── engine.py           # Event engine
│   ├── websocket/              # WebSocket infrastructure
│   │   ├── __init__.py
│   │   ├── manager.py          # Connection management
│   │   └── handlers.py         # Data type handlers
│   ├── dashboard/              # Dashboard service
│   │   ├── __init__.py
│   │   └── service.py          # Status aggregation
│   └── services/               # Business logic
│       ├── __init__.py
│       └── health_monitor.py   # Health monitoring
├── migrations/                 # Database migrations
│   └── init_schema.sql         # Initial schema
└── tests/                      # Test suite
    ├── __init__.py
    └── test_health.py          # Health endpoint tests
```

## Quick Start

### Prerequisites

- Python 3.12+
- Docker and Docker Compose
- PostgreSQL 16 (via Docker)
- Redis 7 (via Docker)

### Environment Setup

1. Clone the repository:
```bash
git clone <repository-url>
cd wti-trading-bot
```

2. Create environment file:
```bash
cp .env.example .env
# Edit .env with your configuration
```

3. Start infrastructure services:
```bash
docker-compose up -d postgres redis
```

4. Install Python dependencies:
```bash
pip install -e ".[dev]"
```

5. Run the application:
```bash
# Development mode with auto-reload
WTI_API__RELOAD=true python -m src.main

# Or using the CLI
wti-bot
```

### Docker Deployment

Run the entire stack with Docker Compose:

```bash
# Start all services
docker-compose up -d

# View logs
docker-compose logs -f app

# Stop all services
docker-compose down
```

Optional monitoring stack:
```bash
# Start with Prometheus and Grafana
docker-compose --profile monitoring up -d
```

## Configuration

All configuration is done through environment variables with the `WTI_` prefix.

### Key Configuration Options

| Variable | Description | Default |
|----------|-------------|---------|
| `WTI_ENVIRONMENT` | Deployment environment | `development` |
| `WTI_TRADING__MODE` | Trading mode: `paper` or `live` | `paper` |
| `WTI_DATABASE__ASYNC_URL` | PostgreSQL async connection URL | - |
| `WTI_REDIS__URL` | Redis connection URL | `redis://localhost:6379/0` |
| `WTI_API__PORT` | API server port | `8000` |
| `WTI_LOG_LEVEL` | Logging level | `INFO` |

See `.env.example` for complete configuration options.

## API Endpoints

### Health Checks

- `GET /health` - Overall system health
- `GET /health/ready` - Kubernetes readiness probe
- `GET /health/live` - Kubernetes liveness probe
- `GET /health/db` - Database connectivity
- `GET /health/redis` - Redis connectivity

### System

- `GET /system/status` - System status overview
- `GET /system/config` - Safe configuration display
- `GET /system/version` - Version information
- `POST /system/kill-switch` - Emergency trading halt
- `GET /system/kill-switch` - Kill switch status
- `POST /system/kill-switch/reset` - Reset kill switch

### Metrics

- `GET /metrics` - Prometheus metrics

### Dashboard

- `GET /api/v1/dashboard/status` - Complete system status
- `GET /api/v1/dashboard/symbol/{symbol}` - Symbol overview (price, position, orders)
- `GET /api/v1/dashboard/performance` - Trading performance summary
- `GET /api/v1/dashboard/signals` - Recent trading signals
- `GET /api/v1/dashboard/orders` - Recent orders
- `GET /api/v1/dashboard/fills` - Recent order fills
- `GET /api/v1/dashboard/risk` - Current risk metrics
- `GET /api/v1/dashboard/events` - Upcoming economic events
- `GET /api/v1/dashboard/system/metrics` - System resource metrics (CPU, memory, disk)

### WebSocket

WebSocket endpoints for real-time data streaming:

- `WS /ws/` - Main WebSocket endpoint (subscribe to any data type)
- `WS /ws/market-data` - Market data stream (ticks and bars)
- `WS /ws/signals` - Trading signals stream
- `WS /ws/orders` - Order updates and fills
- `WS /ws/positions` - Position updates

**Subscription Message Format:**
```json
{
  "action": "subscribe",
  "type": "market_data"
}
```

**Available Subscription Types:**
- `market_data` - Real-time ticks and bars
- `signals` - Trading signals
- `orders` - Order updates and fills
- `positions` - Position updates
- `system` - System status updates
- `alerts` - System alerts

## Development

### Code Quality

```bash
# Format code
black src tests

# Lint code
ruff check src tests

# Type checking
mypy src

# Run all checks
black src tests && ruff check src tests && mypy src
```

### Testing

```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=src --cov-report=html

# Run specific test file
pytest tests/test_health.py -v
```

### Database Migrations

```bash
# Create new migration (using Alembic)
alembic revision --autogenerate -m "description"

# Apply migrations
alembic upgrade head

# Rollback
alembic downgrade -1
```

## Phase Roadmap

### Phase 1: Foundation (Current)
- [x] Project structure and scaffolding
- [x] Database schema design
- [x] Configuration management
- [x] Logging infrastructure
- [x] Health monitoring
- [x] API framework

### Phase 2: Market Data
- [x] Market data feed integration
- [x] Tick aggregation engine
- [x] OHLCV bar generation
- [x] Feed anomaly detection
- [x] WebSocket market data streaming (Redis pub/sub)
- [x] Simulated feed for testing
- [x] Feed health monitoring with heartbeat
- [x] Cross-feed anomaly detection

### Phase 3: Core Strategy Engine
- [x] Event bus for internal pub/sub
- [x] Signal model with comprehensive scoring
- [x] Liquidity sweep detector
- [x] Breakout detector
- [x] Correlation engine
- [x] Fake spike filter
- [x] Strategy engine orchestration
- [x] Signal lifecycle management

### Phase 4: Risk and Execution
- [x] Paper broker for simulated trading
- [x] Order models with lifecycle management
- [x] Position tracking with P&L
- [x] Order sizing logic
- [x] Stop-loss / take-profit management
- [x] Trailing stop support
- [x] Slippage guard
- [x] Spread filter
- [x] Max loss per trade
- [x] Daily drawdown limit
- [x] Max trades per day
- [x] Cooldown after losses
- [x] Kill switch integration
- [x] Execution audit trail

### Phase 5: Event/News Engine
- [x] Economic event calendar
- [x] EIA inventory release scheduling
- [x] OPEC meeting tracking
- [x] FOMC event support
- [x] Event window management
- [x] Pre/post event logic
- [x] Trading lockouts during events
- [x] Position size adjustment for events
- [x] Breakout mode activation
- [x] Event result tracking

### Phase 6: Dashboard/API
- [x] WebSocket manager for real-time streaming
- [x] Market data WebSocket handler
- [x] Signal WebSocket handler
- [x] Order WebSocket handler
- [x] Position WebSocket handler
- [x] System status WebSocket handler
- [x] Dashboard service for status aggregation
- [x] Dashboard REST API endpoints
- [x] Symbol overview endpoint
- [x] Performance summary endpoint
- [x] Risk metrics endpoint
- [x] Upcoming events endpoint
- [x] System metrics endpoint

### Phase 7: Production Hardening (Current)
- [x] Circuit breaker pattern for external services
- [x] Exponential backoff retry mechanism
- [x] Bulkhead pattern for resource isolation
- [x] Token bucket rate limiting
- [x] Sliding window rate limiting
- [x] Distributed rate limiting with Redis
- [x] Security headers middleware (CSP, HSTS, X-Frame-Options)
- [x] Input validation and sanitization middleware
- [x] SQL injection detection
- [x] XSS attack detection
- [x] Path traversal protection
- [x] Request size limits
- [x] Audit logging with tamper-evident chain
- [x] Data retention policies
- [x] Automated data archival
- [x] Database backup and restore
- [x] Encrypted secrets management
- [x] Environment secrets loader
- [x] AWS/Azure secrets loader support
- [x] Secrets rotation support

## Risk Disclaimer

**IMPORTANT**: Trading futures carries substantial risk of loss and is not suitable for all investors. Past performance is not indicative of future results. This software is provided for educational and research purposes only.

- Always start with paper trading
- Never risk more than you can afford to lose
- Use appropriate position sizing
- Monitor your systems continuously
- Have a kill switch ready

## License

MIT License - See LICENSE file for details.

## Contributing

Contributions are welcome! Please read our contributing guidelines and submit pull requests.

## Support

For issues and feature requests, please use the GitHub issue tracker.
