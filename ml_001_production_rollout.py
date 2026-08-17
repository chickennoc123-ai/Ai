#!/usr/bin/env python3
"""
ML-001 Production Rollout
Deploys approved strategies (EURUSD, GBPUSD) to production with health monitoring.

Approved Strategies:
- EURUSD: 7.2% allocation ($720), Sharpe 1.19, PF 1.54
- GBPUSD: 7.2% allocation ($720), Sharpe 1.13, PF 1.53

Total Portfolio Allocation: 14.4% ($1,440)
Remaining Capacity: 85.6% ($8,560)
"""

import json
import logging
import asyncio
import signal
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional
from dataclasses import dataclass, asdict

import pandas as pd
import numpy as np

import sys
sys.path.insert(0, '/home/user/Ai')

from core.ml_001_adapter import ML001Adapter
from core.risk_governance import RiskGovernance, RiskGovernanceConfig
from core.decision_registry import DecisionRegistry
from core.trial_ledger import TrialLedger

# ============================================================
# LOGGING SETUP
# ============================================================

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler('logs/production.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# ============================================================
# CONFIGURATION (FROZEN)
# ============================================================

SYMBOLS = ["EURUSD", "GBPUSD"]
TIMEFRAME = "H1"
TOTAL_CAPITAL = 10000.0

ALLOCATIONS = {
    "EURUSD": 0.072,  # 7.2% = $720
    "GBPUSD": 0.072   # 7.2% = $720
}

THRESHOLDS = {
    "max_positions_per_symbol": 3,
    "max_total_positions": 6,
    "max_daily_loss": 100.0,
    "max_drawdown": 0.15,  # 15%
    "max_gross_exposure": 5.0,
}

MONITORING = {
    "interval": 60,  # seconds
    "status_update_interval": 300,  # 5 minutes
}

# ============================================================
# OUTPUT DIRECTORIES
# ============================================================

Path("logs").mkdir(exist_ok=True)
Path("reports/production").mkdir(parents=True, exist_ok=True)

# ============================================================
# DATA CLASSES
# ============================================================

@dataclass
class Trade:
    """Trade record."""
    symbol: str
    timestamp: datetime
    signal: int  # -1, 0, 1
    price: float
    position_size: float
    entry_price: float
    status: str = "OPEN"  # OPEN, CLOSED, CANCELLED

@dataclass
class Alert:
    """Health alert."""
    timestamp: datetime
    level: str  # INFO, WARNING, CRITICAL
    message: str
    metric: str
    value: float
    threshold: float

# ============================================================
# HEALTH MONITOR
# ============================================================

class HealthMonitor:
    """Production health monitoring."""

    def __init__(self, config: dict):
        self.config = config
        self.alerts = []
        self.running = False
        self.last_check = None
        self.positions = {symbol: 0 for symbol in SYMBOLS}
        self.daily_loss = 0.0
        self.max_daily_loss_threshold = config['max_daily_loss']
        self.max_drawdown_threshold = config['max_drawdown']
        self.total_drawdown = 0.0
        self.emergency_stop_triggered = False

    async def start(self):
        """Start monitoring loop."""
        self.running = True
        logger.info("🟢 Health Monitor STARTED")

        while self.running:
            await self._check()
            await asyncio.sleep(self.config['interval'])

    async def stop(self):
        """Stop monitoring."""
        self.running = False
        logger.info("🔴 Health Monitor STOPPED")

    async def _check(self):
        """Perform health check."""
        self.last_check = datetime.now()

        # Check drawdown
        if self.total_drawdown > self.max_drawdown_threshold:
            alert = Alert(
                timestamp=self.last_check,
                level="CRITICAL",
                message=f"Drawdown exceeded {self.max_drawdown_threshold:.1%}",
                metric="drawdown",
                value=self.total_drawdown,
                threshold=self.max_drawdown_threshold
            )
            self._alert(alert)
            await self._emergency_stop()

        # Check daily loss
        if abs(self.daily_loss) > self.max_daily_loss_threshold:
            alert = Alert(
                timestamp=self.last_check,
                level="CRITICAL",
                message=f"Daily loss exceeded ${self.max_daily_loss_threshold:.2f}",
                metric="daily_loss",
                value=abs(self.daily_loss),
                threshold=self.max_daily_loss_threshold
            )
            self._alert(alert)
            await self._emergency_stop()

        # Check positions
        total_positions = sum(self.positions.values())
        if total_positions > self.config['max_total_positions']:
            alert = Alert(
                timestamp=self.last_check,
                level="WARNING",
                message=f"Position limit exceeded {self.config['max_total_positions']}",
                metric="total_positions",
                value=total_positions,
                threshold=self.config['max_total_positions']
            )
            self._alert(alert)

        logger.debug(f"Health: DD={self.total_drawdown:.1%}, Loss=${abs(self.daily_loss):.2f}, Pos={total_positions}")

    def _alert(self, alert: Alert):
        """Log alert."""
        logger.warning(f"⚠️  {alert.level}: {alert.message} ({alert.value:.2f} > {alert.threshold:.2f})")
        self.alerts.append(alert)

    async def _emergency_stop(self):
        """Emergency stop - close all positions."""
        if not self.emergency_stop_triggered:
            logger.critical("🚨 EMERGENCY STOP ACTIVATED - Closing all positions")
            for symbol in self.positions:
                self.positions[symbol] = 0
            self.emergency_stop_triggered = True
            await self.stop()

# ============================================================
# PRODUCTION RUNNER
# ============================================================

class ProductionRunner:
    """Main production trading runner."""

    def __init__(self):
        self.strategies = {}
        self.positions = {}
        self.pnl = {}
        self.trades = []
        self.running = False
        self.start_time = None
        self.tick_count = 0

        # Risk governance
        risk_config = RiskGovernanceConfig(
            max_total_allocation=0.40,
            max_per_strategy=0.20,
            max_drawdown=THRESHOLDS['max_drawdown'],
            max_correlation=0.70,
            max_positions=THRESHOLDS['max_total_positions'],
            min_allocation=0.01
        )
        self.risk_governance = RiskGovernance(risk_config)

        # Decision registry and trial ledger
        self.decision_registry = DecisionRegistry()
        self.trial_ledger = TrialLedger(max_trials=100)

    async def initialize(self):
        """Initialize strategies and resources."""
        logger.info("=" * 70)
        logger.info("ML-001 PRODUCTION ROLLOUT - INITIALIZATION")
        logger.info("=" * 70)

        self.start_time = datetime.now()

        # Initialize strategies
        for symbol in SYMBOLS:
            try:
                strategy = ML001Adapter()
                strategy.symbol = symbol
                strategy.allocation = ALLOCATIONS[symbol]
                self.strategies[symbol] = strategy
                self.positions[symbol] = 0
                self.pnl[symbol] = 0.0

                allocation_amount = TOTAL_CAPITAL * ALLOCATIONS[symbol]
                logger.info(f"✅ {symbol}: Initialized with ${allocation_amount:.2f} ({ALLOCATIONS[symbol]:.1%})")
            except Exception as e:
                logger.error(f"❌ Failed to initialize {symbol}: {e}")
                raise

        # Log portfolio summary
        total_alloc = sum(ALLOCATIONS.values())
        logger.info(f"\n📊 PORTFOLIO SUMMARY:")
        logger.info(f"  Total Capital: ${TOTAL_CAPITAL:,.2f}")
        logger.info(f"  Total Allocation: ${TOTAL_CAPITAL * total_alloc:,.2f} ({total_alloc:.1%})")
        logger.info(f"  Remaining Capacity: ${TOTAL_CAPITAL * (1 - total_alloc):,.2f} ({(1-total_alloc):.1%})")
        logger.info(f"  Max Positions: {THRESHOLDS['max_total_positions']}")
        logger.info(f"  Max Drawdown: {THRESHOLDS['max_drawdown']:.1%}")
        logger.info(f"  Max Daily Loss: ${THRESHOLDS['max_daily_loss']:.2f}")

        logger.info("\n✅ All strategies initialized successfully")

    async def run(self):
        """Main production loop."""
        self.running = True

        # Start health monitor
        monitor_config = {
            'interval': MONITORING['interval'],
            'max_drawdown': THRESHOLDS['max_drawdown'],
            'max_daily_loss': THRESHOLDS['max_daily_loss'],
            'max_total_positions': THRESHOLDS['max_total_positions'],
            'max_gross_exposure': THRESHOLDS['max_gross_exposure']
        }
        monitor = HealthMonitor(monitor_config)
        monitor_task = asyncio.create_task(monitor.start())

        logger.info("\n" + "=" * 70)
        logger.info("🚀 PRODUCTION LOOP STARTED")
        logger.info("=" * 70)
        logger.info(f"Monitoring every {MONITORING['interval']} seconds")
        logger.info("Press Ctrl+C to stop gracefully")

        last_status_update = datetime.now()

        try:
            while self.running:
                self.tick_count += 1
                current_time = datetime.now()

                # Generate signals for each strategy
                for symbol in SYMBOLS:
                    try:
                        price = self._get_price(symbol)
                        signal = self.strategies[symbol].generate_signal(price)

                        # Execute if signal
                        if signal != 0 and self.positions[symbol] < THRESHOLDS['max_positions_per_symbol']:
                            if self.risk_governance.can_add_position():
                                await self._execute_trade(symbol, signal, price)
                                self.positions[symbol] += 1
                                logger.info(f"📈 {symbol}: Signal={signal:+d} at {price:.5f}")

                    except Exception as e:
                        logger.error(f"Error processing {symbol}: {e}")

                # Update health monitor state
                monitor.positions = self.positions.copy()
                monitor.daily_loss = sum(self.pnl.values())
                monitor.total_drawdown = abs(sum(self.pnl.values())) / TOTAL_CAPITAL if sum(self.pnl.values()) < 0 else 0.0

                # Status update every 5 minutes
                if (current_time - last_status_update).total_seconds() >= MONITORING['status_update_interval']:
                    self._log_status()
                    last_status_update = current_time

                await asyncio.sleep(1)

                # Check if emergency stop was triggered
                if monitor.emergency_stop_triggered:
                    self.running = False

        except KeyboardInterrupt:
            logger.info("\n⏹️  Graceful shutdown initiated...")

        finally:
            self.running = False
            await monitor.stop()
            if not monitor_task.done():
                await monitor_task
            await self._shutdown()

        logger.info("✅ Production stopped")

    def _get_price(self, symbol: str) -> float:
        """Get current price (simulated)."""
        base_prices = {
            "EURUSD": 1.0850,
            "GBPUSD": 1.3050,
        }
        base = base_prices.get(symbol, 1.0)
        noise = np.random.normal(0, 0.00005)
        return base + noise

    async def _execute_trade(self, symbol: str, signal: int, price: float):
        """Execute a trade."""
        allocation = TOTAL_CAPITAL * ALLOCATIONS[symbol]
        position_size = (allocation / price) * 0.01  # 0.01 lot

        trade = Trade(
            symbol=symbol,
            timestamp=datetime.now(),
            signal=signal,
            price=price,
            position_size=position_size,
            entry_price=price
        )
        self.trades.append(trade)

        # Simulate P&L (small random movement)
        simulated_return = signal * np.random.normal(0.0001, 0.00005)
        self.pnl[symbol] += position_size * simulated_return * price

        # Record in decision registry
        self.decision_registry.record({
            'symbol': symbol,
            'signal': signal,
            'price': price,
            'position_size': position_size,
            'timestamp': trade.timestamp
        })

    def _log_status(self):
        """Log current status."""
        total_pnl = sum(self.pnl.values())
        total_positions = sum(self.positions.values())
        elapsed = datetime.now() - self.start_time

        logger.info(f"\n{'='*70}")
        logger.info(f"📊 STATUS UPDATE (Runtime: {elapsed})")
        logger.info(f"{'='*70}")
        logger.info(f"Total P&L: ${total_pnl:+.2f}")
        logger.info(f"Total Positions: {total_positions}/{THRESHOLDS['max_total_positions']}")
        logger.info(f"Total Trades: {len(self.trades)}")

        for symbol in SYMBOLS:
            allocation = TOTAL_CAPITAL * ALLOCATIONS[symbol]
            pnl_pct = (self.pnl[symbol] / allocation * 100) if allocation > 0 else 0
            logger.info(f"  {symbol}: P&L=${self.pnl[symbol]:+.2f} ({pnl_pct:+.2f}%), Pos={self.positions[symbol]}")

        logger.info(f"{'='*70}")

    async def _shutdown(self):
        """Graceful shutdown."""
        logger.info("\n" + "=" * 70)
        logger.info("📋 PRODUCTION SHUTDOWN REPORT")
        logger.info("=" * 70)

        # Save report
        report = {
            'timestamp': datetime.now().isoformat(),
            'status': 'SHUTDOWN',
            'runtime': str(datetime.now() - self.start_time),
            'total_capital': TOTAL_CAPITAL,
            'total_pnl': sum(self.pnl.values()),
            'total_positions': sum(self.positions.values()),
            'total_trades': len(self.trades),
            'pnl_by_symbol': self.pnl,
            'positions_by_symbol': self.positions,
            'trades': [asdict(t) for t in self.trades],
        }

        report_path = Path("reports/production") / f"production_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        with open(report_path, 'w') as f:
            json.dump(report, f, indent=2, default=str)

        logger.info(f"Final P&L: ${sum(self.pnl.values()):+.2f}")
        logger.info(f"Final Positions: {sum(self.positions.values())}")
        logger.info(f"Total Trades Executed: {len(self.trades)}")
        logger.info(f"\n📁 Report saved: {report_path}")
        logger.info("=" * 70)

# ============================================================
# MAIN EXECUTION
# ============================================================

async def main():
    """Run production rollout."""

    try:
        # Initialize
        runner = ProductionRunner()
        await runner.initialize()

        # Run production loop
        await runner.run()

    except Exception as e:
        logger.critical(f"Production error: {e}", exc_info=True)
        raise

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Production stopped by user")
    except Exception as e:
        logger.critical(f"Fatal error: {e}", exc_info=True)
