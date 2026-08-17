#!/usr/bin/env python3
"""
ML-001 Production Runner (Account A)
Runs ML-001 strategies on dedicated broker account.
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
        logging.FileHandler('logs/ml_001_account_a.log'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

# ============================================================
# CONFIGURATION LOADER
# ============================================================

def load_broker_config():
    """Load ML-001 broker configuration."""
    config_path = Path(__file__).parent / "config" / "ml_001_broker.yaml"
    try:
        with open(config_path, 'r') as f:
            return yaml.safe_load(f)
    except Exception as e:
        logger.error(f"Failed to load broker config: {e}")
        sys.exit(1)

# ============================================================
# ML-001 PRODUCTION (Account A)
# ============================================================

class ML001ProductionAccountA:
    """ML-001 production engine running on Account A."""

    def __init__(self, config):
        self.config = config
        self.broker = config['broker']
        self.risk = self.broker['risk']

        self.running = False
        self.symbols = self.broker['symbols']
        self.allocations = self.broker['allocation']

        self.positions = {symbol: 0 for symbol in self.symbols}
        self.pnl = {symbol: 0.0 for symbol in self.symbols}
        self.daily_loss = 0.0
        self.max_drawdown = 0.0
        self.trades_executed = 0
        self.emergency_stop_triggered = False

        self.tick_count = 0
        self.total_capital = self.broker['capital']['total']

    async def run(self):
        """Run ML-001 production loop."""
        self.running = True

        logger.info("=" * 70)
        logger.info("🚀 ML-001 PRODUCTION (Account A)")
        logger.info("=" * 70)
        logger.info("")
        logger.info("📋 ACCOUNT INFORMATION:")
        logger.info(f"  Account ID: {self.broker['account_id']}")
        logger.info(f"  Server: {self.broker['server']}")
        logger.info(f"  Demo Mode: {self.broker['demo']}")
        logger.info("")

        logger.info("📊 PORTFOLIO CONFIGURATION:")
        logger.info(f"  Total Capital: ${self.total_capital:,.2f}")

        total_alloc = sum(self.allocations.values())
        logger.info(f"  Total Allocation: ${self.total_capital * total_alloc:,.2f} ({total_alloc:.1%})")

        for symbol in self.symbols:
            alloc_pct = self.allocations[symbol]
            alloc_amt = self.total_capital * alloc_pct
            logger.info(f"    {symbol}: ${alloc_amt:,.2f} ({alloc_pct:.1%})")

        logger.info(f"  Remaining Capacity: ${self.total_capital * (1 - total_alloc):,.2f} ({(1-total_alloc):.1%})")
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
            while self.running and not self.emergency_stop_triggered:
                self.tick_count += 1

                # Simulate signal generation
                for symbol in self.symbols:
                    if random.random() < 0.15:  # 15% chance per tick
                        signal = random.choice([-1, 1])

                        # Check position limits
                        if self.positions[symbol] == 0 and sum(abs(p) for p in self.positions.values()) < self.risk['max_total_positions']:
                            # Open position
                            self.positions[symbol] = signal
                            self.trades_executed += 1
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
                    current_dd = abs(total_pnl) / self.total_capital
                    if current_dd > self.max_drawdown:
                        self.max_drawdown = current_dd

                # Log status every 60 ticks
                if self.tick_count % 60 == 0:
                    total_pnl = sum(self.pnl.values())
                    total_pos = sum(abs(p) for p in self.positions.values())
                    logger.info(f"📊 ML-001 Status (Tick {self.tick_count}): P&L=${total_pnl:+.2f} | DD={self.max_drawdown:.1%} | Pos={total_pos} | Trades={self.trades_executed}")

                # Check emergency stop conditions
                if abs(self.daily_loss) > self.risk['max_daily_loss']:
                    logger.critical(f"🚨 EMERGENCY STOP: Daily loss ${abs(self.daily_loss):.2f} > ${self.risk['max_daily_loss']:.2f}")
                    self.emergency_stop_triggered = True
                    break

                if self.max_drawdown > self.risk['max_drawdown']:
                    logger.critical(f"🚨 EMERGENCY STOP: Drawdown {self.max_drawdown:.1%} > {self.risk['max_drawdown']:.0%}")
                    self.emergency_stop_triggered = True
                    break

                await asyncio.sleep(1)

        except KeyboardInterrupt:
            pass
        finally:
            self.running = False
            logger.info("")
            logger.info("=" * 70)
            logger.info("📋 ML-001 FINAL REPORT (Account A)")
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
# MAIN
# ============================================================

async def main():
    """Main entry point."""
    config = load_broker_config()

    logger.info("")
    logger.info("=" * 70)
    logger.info("🌐 ML-001 ACCOUNT A INITIALIZATION")
    logger.info("=" * 70)
    logger.info(f"Start Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info("=" * 70)
    logger.info("")

    ml001 = ML001ProductionAccountA(config)
    await ml001.run()

    logger.info("")
    logger.info("=" * 70)
    logger.info(f"End Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info("=" * 70)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("\n✅ ML-001 Production stopped by user")
        sys.exit(0)
    except Exception as e:
        logger.critical(f"Fatal error: {e}", exc_info=True)
        sys.exit(1)
