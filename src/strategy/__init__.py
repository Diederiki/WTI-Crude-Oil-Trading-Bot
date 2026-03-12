"""Strategy engine for signal generation.

Provides pluggable strategy framework with detectors for various
trading setups including liquidity sweeps, breakouts, and correlations.
"""

from src.strategy.models.signal import Signal, SignalType, SignalStatus, SignalScore
from src.strategy.engine import StrategyEngine

__all__ = [
    "Signal",
    "SignalType", 
    "SignalStatus",
    "SignalScore",
    "StrategyEngine",
]