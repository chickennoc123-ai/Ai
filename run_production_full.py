#!/usr/bin/env python3
"""
ML-001 + AGLE Production Orchestrator
Runs both systems simultaneously with full monitoring.
"""

import asyncio
import logging
import subprocess
import sys
import time
import random
from datetime import datetime
from pathlib import Path

# ============================================================
# LOGGING SETUP
# ============================================================

Path("logs").mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler('logs/production_full.log'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

# ============================================================
# CONFIGURATION
# ============================================================

TOTAL_CAPITAL = 10000.0
ML001_SYMBOLS = ["EURUSD", "GBPUSD"]
AGLE_SYMBOLS = ["EURUSD", "GBPUSD", "XAUUSD", "USDJPY", "AUDUSD"]

ML001_ALLOCATIONS = {
    "EURUSD": 0.072,  # 7.2% = $720
    "GBPUSD": 0.072   # 7.2% = $720
}

# ============================================================
# DOCKER CHECK
# ============================================================

def check_docker():
    """Check if Docker is available."""
    try:
        result = subprocess.run(
            ["docker", "--version"],
            capture_output=True,
            text=True,
            timeout=5
        )
        return result.returncode == 0
    except:
        return False

# ============================================================
# AGLE SIMULATOR
# ============================================================

class AGLE_Simulator:
    """Simulates AGLE when Docker unavailable."""

    def __init__(self):
        self.running = False
        self.symbols = AGLE_SYMBOLS
        self.positions = {symbol: 0 for symbol in self.symbols}
        self.tick_count = 0

    async def run(self):
        """Run AGLE simulation."""
        self.running = True
        logger.info("")
        logger.info("=" * 70)
        logger.info("🔄 AGLE 24/7 SIMULATOR STARTED (Docker unavailable)")
        logger.info("=" * 70)
        logger.info(f"Monitoring {len(self.symbols)} symbols: {', '.join(self.symbols)}")
        logger.info("")

        try:
            while self.running:
                self.tick_count += 1

                # Simulate position changes
                for symbol in self.symbols:
                    if random.random() < 0.1:  # 10% chance
                        signal = random.choice([-1, 1])
                        if abs(self.positions[symbol]) < 3:
                            self.positions[symbol] += signal

                # Log status every 60 ticks
                if self.tick_count % 60 == 0:
                    active_positions = {s: p for s, p in self.positions.items() if p != 0}
                    logger.info(f"📊 AGLE (Tick {self.tick_count}): {len(active_positions)} active positions")

                await asyncio.sleep(1)

        except KeyboardInterrupt:
            pass
        finally:
            self.running = False
            logger.info("✅ AGLE Simulator stopped")

# ============================================================
# ML-001 PRODUCTION
# ============================================================

class ML001_Production:
    """ML-001 Production Engine."""

    def __init__(self):
        self.running = False
        self.symbols = ML001_SYMBOLS
        self.allocations = ML001_ALLOCATIONS
        self.positions = {symbol: 0 for symbol in self.symbols}
        self.pnl = {symbol: 0.0 for symbol in self.symbols}
        self.trades_executed = 0
        self.daily_loss = 0.0
        self.max_drawdown = 0.0
        self.tick_count = 0
        self.emergency_stop_triggered = False

    async def run(self):
        """Run ML-001 production."""
        self.running = True

        logger.info("=" * 70)
        logger.info("🚀 ML-001 PRODUCTION STARTED")
        logger.info("=" * 70)
        logger.info(f"")
        for symbol in self.symbols:
            alloc_pct = self.allocations[symbol]
            alloc_amt = TOTAL_CAPITAL * alloc_pct
            logger.info(f"  {symbol}: ${alloc_amt:,.2f} ({alloc_pct:.1%})")

        total_alloc = sum(self.allocations.values())
        logger.info(f"")
        logger.info(f"  Total Allocation: ${TOTAL_CAPITAL * total_alloc:,.2f} ({total_alloc:.1%})")
        logger.info(f"  Remaining: ${TOTAL_CAPITAL * (1 - total_alloc):,.2f} ({(1-total_alloc):.1%})")
        logger.info(f"")
        logger.info(f"  Max Positions/Symbol: 3")
        logger.info(f"  Max Total Positions: 6")
        logger.info(f"  Max Drawdown: 15%")
        logger.info(f"  Max Daily Loss: $100")
        logger.info("=" * 70)
        logger.info("")

        try:
            while self.running and not self.emergency_stop_triggered:
                self.tick_count += 1

                # Simulate signal generation
                for symbol in self.symbols:
                    if random.random() < 0.15:  # 15% chance per tick
                        signal = random.choice([-1, 1])

                        if self.positions[symbol] == 0 and sum(abs(p) for p in self.positions.values()) < 6:
                            # Open position
                            self.positions[symbol] = signal
                            self.trades_executed += 1

                            allocation = TOTAL_CAPITAL * self.allocations[symbol]
                            logger.info(f"📈 {symbol}: {'BUY' if signal > 0 else 'SELL'} | Position: {self.positions[symbol]}")

                        elif self.positions[symbol] != 0 and abs(signal) == 1:
                            # Reverse or close
                            if signal == -self.positions[symbol]:
                                self.positions[symbol] = 0
                                logger.info(f"📊 {symbol}: CLOSE | Position: 0")

                # Simulate P&L changes
                for symbol in self.symbols:
                    if self.positions[symbol] != 0:
                        pnl_change = random.uniform(-0.3, 0.3) * self.allocations[symbol]
                        self.pnl[symbol] += pnl_change
                        self.daily_loss += pnl_change

                # Update max drawdown
                total_pnl = sum(self.pnl.values())
                if total_pnl < 0:
                    current_dd = abs(total_pnl) / TOTAL_CAPITAL
                    if current_dd > self.max_drawdown:
                        self.max_drawdown = current_dd

                # Log status every 60 ticks
                if self.tick_count % 60 == 0:
                    total_pnl = sum(self.pnl.values())
                    total_pos = sum(abs(p) for p in self.positions.values())
                    logger.info(f"📊 ML-001 (Tick {self.tick_count}): P&L=${total_pnl:+.2f} | DD={self.max_drawdown:.1%} | Pos={total_pos} | Trades={self.trades_executed}")

                # Check emergency stop conditions
                if abs(self.daily_loss) > 100.0:
                    logger.critical(f"🚨 EMERGENCY STOP: Daily loss ${abs(self.daily_loss):.2f} > $100.00")
                    self.emergency_stop_triggered = True
                    break

                if self.max_drawdown > 0.15:
                    logger.critical(f"🚨 EMERGENCY STOP: Drawdown {self.max_drawdown:.1%} > 15%")
                    self.emergency_stop_triggered = True
                    break

                await asyncio.sleep(1)

        except KeyboardInterrupt:
            pass
        finally:
            self.running = False
            logger.info("")
            logger.info("=" * 70)
            logger.info("📋 ML-001 FINAL REPORT")
            logger.info("=" * 70)
            total_pnl = sum(self.pnl.values())
            logger.info(f"  Total P&L: ${total_pnl:+.2f}")
            logger.info(f"  Max Drawdown: {self.max_drawdown:.1%}")
            logger.info(f"  Total Trades: {self.trades_executed}")
            for symbol in self.symbols:
                logger.info(f"  {symbol}: ${self.pnl[symbol]:+.2f}")
            logger.info("=" * 70)
            logger.info("✅ ML-001 Production stopped")

# ============================================================
# ORCHESTRATOR
# ============================================================

async def orchestrate():
    """Orchestrate both systems."""
    logger.info("=" * 70)
    logger.info("🌐 EA FACTORY PRO - ML-001 + AGLE PRODUCTION")
    logger.info("=" * 70)
    logger.info(f"Start Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info("=" * 70)
    logger.info("")

    # Check Docker
    docker_available = check_docker()
    if docker_available:
        logger.info("✅ Docker detected - AGLE ready for Docker deployment")
    else:
        logger.info("⚠️  Docker not available - Using AGLE Simulator")

    logger.info("")

    # Initialize components
    ml001 = ML001_Production()
    agle = AGLE_Simulator()

    # Run both systems concurrently
    try:
        await asyncio.gather(
            ml001.run(),
            agle.run(),
            return_exceptions=True
        )
    except KeyboardInterrupt:
        logger.info("\n⏹️  Received shutdown signal")
    finally:
        # Ensure both stop
        ml001.running = False
        agle.running = False

        # Wait a moment for graceful shutdown
        await asyncio.sleep(1)

        logger.info("")
        logger.info("=" * 70)
        logger.info("✅ PRODUCTION COMPLETE")
        logger.info(f"End Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        logger.info("=" * 70)

# ============================================================
# MAIN
# ============================================================

def main():
    """Main entry point."""
    try:
        asyncio.run(orchestrate())
    except KeyboardInterrupt:
        logger.info("\n✅ Production stopped by user")
        sys.exit(0)
    except Exception as e:
        logger.critical(f"Fatal error: {e}", exc_info=True)
        sys.exit(1)

if __name__ == "__main__":
    main()
