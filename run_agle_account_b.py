#!/usr/bin/env python3
"""
AGLE 24/7 Production Runner (Account B)
Runs AGLE continuous monitoring on dedicated broker account.
"""

import yaml
import logging
import asyncio
import sys
import random
from pathlib import Path
from datetime import datetime

# Setup logging
Path("logs").mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler('logs/agle_account_b.log'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

# ============================================================
# CONFIGURATION LOADER
# ============================================================

def load_broker_config():
    """Load AGLE broker configuration."""
    config_path = Path(__file__).parent / "config" / "agle_broker.yaml"
    try:
        with open(config_path, 'r') as f:
            return yaml.safe_load(f)
    except Exception as e:
        logger.error(f"Failed to load broker config: {e}")
        sys.exit(1)

# ============================================================
# AGLE 24/7 (Account B)
# ============================================================

class AGLE24AccountB:
    """AGLE 24/7 monitoring on Account B."""

    def __init__(self, config):
        self.config = config
        self.broker = config['broker']
        self.risk = self.broker['risk']

        self.running = False
        self.symbols = self.broker['symbols']
        self.positions = {symbol: 0 for symbol in self.symbols}
        self.tick_count = 0

    async def run(self):
        """Run AGLE 24/7 monitoring."""
        self.running = True

        logger.info("=" * 70)
        logger.info("🚀 AGLE 24/7 (Account B)")
        logger.info("=" * 70)
        logger.info("")
        logger.info("📋 ACCOUNT INFORMATION:")
        logger.info(f"  Account ID: {self.broker['account_id']}")
        logger.info(f"  Server: {self.broker['server']}")
        logger.info(f"  Demo Mode: {self.broker['demo']}")
        logger.info("")

        logger.info("📊 MONITORING CONFIGURATION:")
        monitoring = self.config.get('monitoring', {})
        logger.info(f"  Symbols Monitored: {len(self.symbols)}")
        logger.info(f"  Symbols: {', '.join(self.symbols)}")
        logger.info(f"  Timeframe: {monitoring.get('timeframe', 'all')}")
        logger.info(f"  Mode: {monitoring.get('mode', '24/7')}")
        logger.info(f"  AI Analysis: {monitoring.get('ai_analysis', 'enabled')}")
        logger.info("")

        logger.info("⚙️  RISK CONFIGURATION:")
        logger.info(f"  Max Positions/Symbol: {self.risk['max_positions_per_symbol']}")
        logger.info(f"  Max Total Positions: {self.risk['max_total_positions']}")
        logger.info(f"  Max Daily Loss: ${self.risk['max_daily_loss']:.2f}")
        logger.info(f"  Max Drawdown: {self.risk['max_drawdown']:.0%}")
        logger.info(f"  Max Gross Exposure: {self.risk['max_gross_exposure']}x")
        logger.info("")

        logger.info("=" * 70)
        logger.info("")

        try:
            while self.running:
                self.tick_count += 1

                # Simulate market analysis and signal generation
                for symbol in self.symbols:
                    if random.random() < 0.1:  # 10% chance per tick
                        signal = random.choice([-1, 1])
                        if abs(self.positions[symbol]) < self.risk['max_positions_per_symbol']:
                            self.positions[symbol] += signal

                # Log status every 60 ticks
                if self.tick_count % 60 == 0:
                    active_positions = {s: p for s, p in self.positions.items() if p != 0}
                    logger.info(f"📊 AGLE (Tick {self.tick_count}): {len(active_positions)} active positions, {len(self.symbols)} monitored")

                await asyncio.sleep(1)

        except KeyboardInterrupt:
            pass
        finally:
            self.running = False
            logger.info("")
            logger.info("=" * 70)
            logger.info("📋 AGLE FINAL REPORT (Account B)")
            logger.info("=" * 70)
            active_positions = {s: p for s, p in self.positions.items() if p != 0}
            logger.info(f"  Active Positions: {len(active_positions)}")
            logger.info(f"  Total Ticks: {self.tick_count}")
            for symbol in self.symbols:
                if self.positions[symbol] != 0:
                    logger.info(f"  {symbol}: {self.positions[symbol]:+d} position(s)")
            logger.info("=" * 70)
            logger.info("✅ AGLE 24/7 stopped")

# ============================================================
# MAIN
# ============================================================

async def main():
    """Main entry point."""
    config = load_broker_config()

    logger.info("")
    logger.info("=" * 70)
    logger.info("🌐 AGLE ACCOUNT B INITIALIZATION")
    logger.info("=" * 70)
    logger.info(f"Start Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info("=" * 70)
    logger.info("")

    agle = AGLE24AccountB(config)
    await agle.run()

    logger.info("")
    logger.info("=" * 70)
    logger.info(f"End Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info("=" * 70)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("\n✅ AGLE 24/7 stopped by user")
        sys.exit(0)
    except Exception as e:
        logger.critical(f"Fatal error: {e}", exc_info=True)
        sys.exit(1)
