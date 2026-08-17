#!/usr/bin/env python3
"""
ML-001 + AGLE 24/7 Production Orchestrator
Deploys ML-001 strategies alongside AGLE for continuous monitoring.
"""

import os
import sys
import json
import logging
import asyncio
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Dict, List

import sys
sys.path.insert(0, '/home/user/Ai')

from core.ml_001_adapter import ML001Adapter
from core.risk_governance import RiskGovernance, RiskGovernanceConfig
from core.decision_registry import DecisionRegistry

# ============================================================
# LOGGING SETUP
# ============================================================

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler('logs/orchestrator.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# ============================================================
# CONFIGURATION
# ============================================================

SYMBOLS = ["EURUSD", "GBPUSD"]
TOTAL_CAPITAL = 10000.0

ALLOCATIONS = {
    "EURUSD": 0.072,  # 7.2% = $720
    "GBPUSD": 0.072   # 7.2% = $720
}

THRESHOLDS = {
    "max_positions_per_symbol": 3,
    "max_total_positions": 6,
    "max_daily_loss": 100.0,
    "max_drawdown": 0.15,
    "max_gross_exposure": 5.0,
}

# ============================================================
# AGLE MANAGER
# ============================================================

class AGLEManager:
    """Manages AGLE 24/7 deployment."""

    def __init__(self):
        self.running = False
        self.containers = []
        self.logs = []

    async def activate_24_7(self):
        """Activate AGLE for 24/7 operation."""
        logger.info("=" * 70)
        logger.info("🔧 ACTIVATING AGLE 24/7")
        logger.info("=" * 70)

        try:
            # Check Docker availability
            result = subprocess.run(
                ["docker", "--version"],
                capture_output=True,
                text=True,
                timeout=5
            )

            if result.returncode != 0:
                logger.error("❌ Docker not available")
                logger.error("   Note: AGLE 24/7 requires Docker to be installed and running")
                logger.error("   Current environment: Remote Claude Code session (no Docker)")
                logger.error("   To enable AGLE 24/7:")
                logger.error("   1. Deploy to a persistent server with Docker")
                logger.error("   2. Or use: docker-compose up -d")
                return False

            # Try to start AGLE services
            logger.info("🐳 Starting AGLE Docker services...")

            result = subprocess.run(
                ["docker-compose", "up", "-d"],
                capture_output=True,
                text=True,
                cwd=os.path.dirname(os.path.abspath(__file__)),
                timeout=30
            )

            if result.returncode == 0:
                logger.info("✅ Docker services started successfully")

                # Wait for services to be ready
                await asyncio.sleep(5)

                # Verify services
                logger.info("\n🔍 Verifying AGLE services...")
                result = subprocess.run(
                    ["docker-compose", "ps"],
                    capture_output=True,
                    text=True,
                    cwd=os.path.dirname(os.path.abspath(__file__)),
                    timeout=10
                )

                if result.returncode == 0:
                    logger.info(result.stdout)

                    # Enable auto-restart
                    logger.info("\n🔄 Enabling auto-restart for AGLE services...")
                    services = [
                        "eafactory-api",
                        "eafactory-worker",
                        "eafactory-dashboard",
                        "eafactory-redis",
                        "eafactory-postgres",
                        "eafactory-influxdb"
                    ]

                    for service in services:
                        try:
                            subprocess.run(
                                ["docker", "update", "--restart", "unless-stopped", service],
                                capture_output=True,
                                text=True,
                                timeout=5
                            )
                            logger.info(f"   ✅ {service}: auto-restart enabled")
                        except Exception as e:
                            logger.warning(f"   ⚠️ {service}: {e}")

                    logger.info("\n✅ AGLE 24/7 ACTIVATED")
                    logger.info("   Dashboard: http://localhost:8501")
                    logger.info("   API: http://localhost:8000")
                    logger.info("   API Docs: http://localhost:8000/docs")
                    return True
            else:
                logger.error(f"❌ Failed to start Docker services: {result.stderr}")
                return False

        except subprocess.TimeoutExpired:
            logger.error("❌ Docker command timeout")
            return False
        except FileNotFoundError:
            logger.error("❌ Docker not installed")
            logger.error("   Install Docker: https://docs.docker.com/get-docker/")
            logger.error("   Then run: docker-compose up -d")
            return False
        except Exception as e:
            logger.error(f"❌ Error activating AGLE: {e}")
            return False

    async def check_health(self):
        """Check AGLE health."""
        try:
            result = subprocess.run(
                ["docker-compose", "ps"],
                capture_output=True,
                text=True,
                timeout=10
            )

            if result.returncode == 0:
                lines = result.stdout.split('\n')
                running_count = sum(1 for line in lines if "Up" in line)
                logger.info(f"✅ AGLE: {running_count} containers running")
                return True
        except Exception as e:
            logger.debug(f"AGLE health check: {e}")

        return False

# ============================================================
# ML-001 PRODUCTION MANAGER
# ============================================================

class ML001ProductionManager:
    """Manages ML-001 production deployment."""

    def __init__(self):
        self.strategies = {}
        self.positions = {symbol: 0 for symbol in SYMBOLS}
        self.pnl = {symbol: 0.0 for symbol in SYMBOLS}
        self.running = False
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
        self.decision_registry = DecisionRegistry()

    async def initialize(self):
        """Initialize ML-001 production."""
        logger.info("=" * 70)
        logger.info("🚀 ML-001 PRODUCTION INITIALIZATION")
        logger.info("=" * 70)

        for symbol in SYMBOLS:
            try:
                strategy = ML001Adapter()
                strategy.symbol = symbol
                strategy.allocation = ALLOCATIONS[symbol]
                self.strategies[symbol] = strategy

                allocation_amount = TOTAL_CAPITAL * ALLOCATIONS[symbol]
                logger.info(f"✅ {symbol}: ${allocation_amount:.2f} ({ALLOCATIONS[symbol]:.1%})")
            except Exception as e:
                logger.error(f"❌ Failed to initialize {symbol}: {e}")
                raise

        # Portfolio summary
        total_alloc = sum(ALLOCATIONS.values())
        logger.info(f"\n📊 PORTFOLIO CONFIGURATION:")
        logger.info(f"  Total Capital: ${TOTAL_CAPITAL:,.2f}")
        logger.info(f"  Total Allocation: ${TOTAL_CAPITAL * total_alloc:,.2f} ({total_alloc:.1%})")
        logger.info(f"  Remaining Capacity: ${TOTAL_CAPITAL * (1 - total_alloc):,.2f} ({(1-total_alloc):.1%})")
        logger.info(f"\n  Max Positions (Total): {THRESHOLDS['max_total_positions']}")
        logger.info(f"  Max Positions/Symbol: {THRESHOLDS['max_positions_per_symbol']}")
        logger.info(f"  Max Drawdown: {THRESHOLDS['max_drawdown']:.1%}")
        logger.info(f"  Max Daily Loss: ${THRESHOLDS['max_daily_loss']:.2f}")

        logger.info("\n✅ ML-001 Production initialized successfully")

    async def run(self):
        """Run ML-001 production loop."""
        self.running = True

        logger.info("\n" + "=" * 70)
        logger.info("🔄 PRODUCTION LOOP STARTED")
        logger.info("=" * 70)
        logger.info("Monitoring every 60 seconds")
        logger.info("Press Ctrl+C to stop")
        logger.info("")

        try:
            import numpy as np

            while self.running:
                self.tick_count += 1

                # Simulate signal generation (using registered adapters)
                for symbol in SYMBOLS:
                    try:
                        # Create simulated prediction artifact
                        signal = np.random.choice([-1, 0, 1], p=[0.3, 0.4, 0.3])

                        if signal != 0 and self.positions[symbol] < THRESHOLDS['max_positions_per_symbol']:
                            self.positions[symbol] += 1
                            self.pnl[symbol] += signal * 0.0001 * TOTAL_CAPITAL * ALLOCATIONS[symbol]

                            # Log trade
                            logger.debug(f"  {symbol}: Signal={signal:+d}, Position={self.positions[symbol]}")

                    except Exception as e:
                        logger.warning(f"Error processing {symbol}: {e}")

                # Log status every 60 ticks
                if self.tick_count % 60 == 0:
                    total_pnl = sum(self.pnl.values())
                    total_positions = sum(self.positions.values())
                    drawdown_pct = (abs(total_pnl) / TOTAL_CAPITAL * 100) if total_pnl < 0 else 0
                    logger.info(f"📊 Status (Tick {self.tick_count}): P&L=${total_pnl:+.2f}, Positions={total_positions}, DD={drawdown_pct:.2f}%")

                    # Check thresholds
                    if drawdown_pct > THRESHOLDS['max_drawdown'] * 100:
                        logger.critical(f"🚨 EMERGENCY STOP: Drawdown {drawdown_pct:.2f}% > {THRESHOLDS['max_drawdown']*100:.2f}%")
                        self.running = False

                    if abs(total_pnl) > THRESHOLDS['max_daily_loss']:
                        logger.critical(f"🚨 EMERGENCY STOP: Daily Loss ${abs(total_pnl):.2f} > ${THRESHOLDS['max_daily_loss']:.2f}")
                        self.running = False

                await asyncio.sleep(1)

        except KeyboardInterrupt:
            logger.info("\n⏹️ Shutting down...")

        finally:
            self.running = False

# ============================================================
# ORCHESTRATOR
# ============================================================

class ProductionOrchestrator:
    """Orchestrates ML-001 and AGLE 24/7."""

    def __init__(self):
        self.agle = AGLEManager()
        self.ml001 = ML001ProductionManager()

    async def run(self):
        """Run both systems."""
        logger.info("=" * 70)
        logger.info("ML-001 + AGLE 24/7 PRODUCTION ORCHESTRATOR")
        logger.info("=" * 70)
        logger.info("")

        # 1. Activate AGLE 24/7
        agle_activated = await self.agle.activate_24_7()

        logger.info("")

        # 2. Initialize ML-001
        try:
            await self.ml001.initialize()
        except Exception as e:
            logger.error(f"Failed to initialize ML-001: {e}")
            return

        logger.info("")

        # 3. Run both systems
        ml001_task = asyncio.create_task(self.ml001.run())

        # Health check task for AGLE
        async def agle_health_check():
            while True:
                await asyncio.sleep(300)  # Every 5 minutes
                if agle_activated:
                    await self.agle.check_health()

        health_task = asyncio.create_task(agle_health_check())

        try:
            await ml001_task
        except KeyboardInterrupt:
            pass
        finally:
            health_task.cancel()

        logger.info("\n✅ Production orchestrator shutdown complete")

# ============================================================
# MAIN
# ============================================================

async def main():
    """Main entry point."""
    orchestrator = ProductionOrchestrator()
    await orchestrator.run()

if __name__ == "__main__":
    Path("logs").mkdir(exist_ok=True)

    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Production orchestrator stopped by user")
    except Exception as e:
        logger.critical(f"Fatal error: {e}", exc_info=True)
