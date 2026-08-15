"""Meta Agent: supervises and tunes the whole platform.

Every cycle the Meta Agent:

1. Collects health from all agents and performance from the broker history.
2. Re-runs the validation gate on the active strategies and updates their
   lifecycle state.
3. Recomputes portfolio allocations with the Decision Engine.
4. Checks whether the platform's own confidence is calibrated against realised
   outcomes, and adapts agent parameters through ``META_FEEDBACK``.

The tuning loop is deliberately conservative: it nudges a small number of
bounded parameters (mutation rate, active strategy set, research budget) rather
than rewriting behaviour.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import numpy as np

from agents.base_agent import BaseAgent
from agents.llm import LLMClient, create_llm_client
from agents.message_bus import Message, MessageType
from core.backtest import BacktestConfig, BacktestEngine
from core.decision import DecisionEngine
from core.lifecycle import LifecycleManager, LifecycleState
from core.strategy_registry import create_strategy
from core.validation import ValidationSuite
from utils.helpers import utcnow


class MetaAgent(BaseAgent):
    """Continuously evaluates and improves the running system."""

    subscriptions = [
        MessageType.RESEARCH_FINDING,
        MessageType.EXECUTION_REPORT,
        MessageType.RISK_ALERT,
        MessageType.COMMAND,
    ]

    def __init__(self, **kwargs: Any) -> None:
        """Initialise the meta agent."""
        super().__init__("meta", **kwargs)
        self.symbols: List[str] = list(self.config.get("broker.xmtrading.symbols", ["EURUSD"]))
        self.timeframe = str(self.config.get("agents.analysis.timeframe", "H1"))
        self.active_strategies: List[str] = list(self.config.get("strategies.active", []))
        self.engine = BacktestEngine(BacktestConfig.from_config(self.config))
        self.suite = ValidationSuite(self.config, self.engine)
        self.lifecycle: Optional[LifecycleManager] = None
        self.decision: Optional[DecisionEngine] = None
        self.llm: Optional[LLMClient] = None
        self.validation_reports: Dict[str, Dict[str, Any]] = {}
        self.allocations: List[Dict[str, Any]] = []
        self.research_findings: List[Dict[str, Any]] = []
        self.calibration: Dict[str, Any] = {}
        self.system_notes: List[str] = []
        self.cycles_completed = 0

    # -- lifecycle -----------------------------------------------------------
    async def initialize(self) -> bool:
        """Wire the shared services used by the supervision loop."""
        self.lifecycle = self.service("lifecycle") or LifecycleManager(self.config)
        self.decision = self.service("decision_engine") or DecisionEngine(self.config, self.lifecycle)
        self.llm = create_llm_client(self.config)
        for name in self.active_strategies:
            for symbol in self.symbols:
                self.lifecycle.register(f"{name}-{symbol}", LifecycleState.ACTIVE, "Configured as active")
        self.logger.info("Meta agent ready", strategies=len(self.active_strategies), symbols=len(self.symbols))
        return True

    async def shutdown(self) -> None:
        """Close the LLM client."""
        if self.llm is not None:
            await self.llm.close()

    async def execute_cycle(self) -> None:
        """Run a full supervision pass."""
        self.cycles_completed += 1
        await self._validate_active_strategies()
        await self._update_allocations()
        self._check_calibration()
        feedback = self._build_feedback()

        await self.publish(
            MessageType.META_FEEDBACK,
            {
                "cycle": self.cycles_completed,
                "timestamp": utcnow().isoformat(),
                **feedback,
            },
        )
        self.logger.info(
            "Meta supervision cycle complete",
            cycle=self.cycles_completed,
            validated=len(self.validation_reports),
            allocated=sum(1 for item in self.allocations if item["allocation"] > 0),
        )

    async def process(self, message: Message) -> Optional[Message]:
        """Absorb research findings, execution reports and risk alerts."""
        if message.message_type is MessageType.RESEARCH_FINDING:
            self.research_findings.append(message.payload)
            self.research_findings = self.research_findings[-50:]
            await self._consider_promotion(message.payload)
        elif message.message_type is MessageType.RISK_ALERT:
            if str(message.payload.get("level")) == "CRITICAL":
                self.system_notes.append(
                    f"{utcnow().isoformat()} risk halt: {message.payload.get('reason', '')}"
                )
                self.system_notes = self.system_notes[-100:]
        elif message.message_type is MessageType.COMMAND:
            if message.payload.get("command") == "meta_cycle":
                await self.execute_cycle()
        return None

    # -- supervision ---------------------------------------------------------
    async def _validate_active_strategies(self) -> None:
        """Re-validate every active strategy and update its lifecycle state."""
        data_manager = self.require_service("data_manager")
        assert self.lifecycle is not None
        for name in list(self.active_strategies):
            for symbol in self.symbols:
                key = f"{name}-{symbol}"
                try:
                    df = await data_manager.get_ohlcv(symbol, self.timeframe, self.config.get_int("data.history_bars", 5000))
                    strategy = create_strategy(name, symbol, self.timeframe)
                    report = self.suite.run(strategy, df, quick=True)
                except Exception as exc:  # noqa: BLE001 - never let one strategy break the loop
                    self.logger.warning("Validation failed", strategy=name, symbol=symbol, error=str(exc))
                    continue
                self.validation_reports[key] = report.to_dict()
                metrics = report.baseline.get("metrics", {})
                self.lifecycle.update_state(key, metrics)

    async def _update_allocations(self) -> None:
        """Recompute the capital allocation across validated strategies."""
        assert self.decision is not None
        account_api = self.service("account")
        capital = self.config.get_float("decision.capital", 10_000.0)
        if account_api is not None:
            try:
                capital = (await account_api.get_info()).equity
            except Exception as exc:  # noqa: BLE001
                self.logger.debug("Could not read equity for allocation", error=str(exc))

        candidates: List[Dict[str, Any]] = []
        for key, report in self.validation_reports.items():
            metrics = report.get("baseline", {}).get("metrics", {})
            candidates.append(
                {
                    "strategy_id": key,
                    "strategy_name": report.get("strategy_name", key),
                    "symbol": report.get("symbol", ""),
                    "metrics": metrics,
                    "validation": report,
                }
            )
        decisions = self.decision.allocate_portfolio(candidates, capital)
        self.allocations = [decision.to_dict() for decision in decisions]

    def _check_calibration(self) -> None:
        """Compare predicted confidence with realised outcomes across reports."""
        predicted: List[float] = []
        observed: List[float] = []
        for report in self.validation_reports.values():
            calibration = report.get("calibration", {})
            for bucket in calibration.get("bins", []):
                predicted.append(float(bucket.get("predicted", 0.0)))
                observed.append(float(bucket.get("observed", 0.0)))
        if not predicted:
            self.calibration = {"samples": 0, "error": None}
            return
        errors = np.abs(np.array(predicted) - np.array(observed))
        self.calibration = {
            "samples": len(predicted),
            "mean_absolute_error": round(float(errors.mean()), 4),
            "worst_bucket_error": round(float(errors.max()), 4),
            "well_calibrated": bool(errors.mean() <= 0.15),
        }

    async def _consider_promotion(self, finding: Dict[str, Any]) -> None:
        """Promote a research candidate that clears the full validation gate."""
        best = finding.get("best") or {}
        name = best.get("strategy")
        symbol = best.get("symbol")
        if not name or not symbol or name in self.active_strategies:
            return
        if float(best.get("score", 0.0)) < 0.55:
            return

        data_manager = self.require_service("data_manager")
        try:
            df = await data_manager.get_ohlcv(symbol, self.timeframe, self.config.get_int("data.history_bars", 5000))
            strategy = create_strategy(name, symbol, self.timeframe, best.get("params"))
            report = self.suite.run(strategy, df, quick=False)
        except Exception as exc:  # noqa: BLE001
            self.logger.warning("Promotion validation failed", strategy=name, error=str(exc))
            return

        self.validation_reports[f"{name}-{symbol}"] = report.to_dict()
        if not report.passed:
            self.logger.info("Candidate rejected by the full gate", strategy=name, reasons=report.reasons[:2])
            return

        self.active_strategies.append(name)
        assert self.lifecycle is not None
        self.lifecycle.register(f"{name}-{symbol}", LifecycleState.DEGRADED, "Promoted on probation")
        self.system_notes.append(f"{utcnow().isoformat()} promoted {name} on {symbol}")
        self.logger.info("Strategy promoted to the active set", strategy=name, symbol=symbol, score=round(report.score, 3))

    def _build_feedback(self) -> Dict[str, Any]:
        """Derive bounded parameter adjustments for the other agents."""
        assert self.lifecycle is not None
        snapshot = self.lifecycle.snapshot()
        healthy = snapshot["counts"].get(LifecycleState.ACTIVE.value, 0)
        degraded = snapshot["counts"].get(LifecycleState.DEGRADED.value, 0)
        paused = snapshot["counts"].get(LifecycleState.PAUSED.value, 0)

        # More pressure on research when the live population is weak.
        weakness = (degraded + 2 * paused) / max(healthy + degraded + paused, 1)
        mutation_rate = round(min(0.6, 0.25 + 0.35 * weakness), 3)
        research_budget = int(min(48, 16 + 32 * weakness))

        tradable = [
            key.split("-")[0]
            for key, record in snapshot["strategies"].items()
            if record["state"] in (LifecycleState.ACTIVE.value, LifecycleState.DEGRADED.value)
        ]
        active_strategies = sorted(set(tradable)) or self.active_strategies

        return {
            "lifecycle": snapshot["counts"],
            "calibration": self.calibration,
            "allocations": self.allocations[:20],
            "research": {"mutation_rate": mutation_rate, "max_candidates": research_budget},
            "analysis": {"active_strategies": active_strategies},
            "notes": self.system_notes[-10:],
        }

    # -- reporting -----------------------------------------------------------
    def report(self) -> Dict[str, Any]:
        """Return the meta-research state for the API and dashboard."""
        assert self.lifecycle is not None
        return {
            "cycles": self.cycles_completed,
            "active_strategies": self.active_strategies,
            "lifecycle": self.lifecycle.snapshot(),
            "allocations": self.allocations,
            "calibration": self.calibration,
            "validation_reports": {
                key: {
                    "passed": report.get("passed"),
                    "score": round(float(report.get("score", 0.0)), 4),
                    "sharpe": round(float(report.get("baseline", {}).get("metrics", {}).get("sharpe", 0.0)), 3),
                    "pbo": (
                        round(float(report.get("pbo", {}).get("pbo", 0.0)), 3)
                        if report.get("pbo", {}).get("computed")
                        else None
                    ),
                    "wfa_efficiency": round(float(report.get("walk_forward", {}).get("efficiency", 0.0)), 3),
                    "reasons": report.get("reasons", []),
                }
                for key, report in self.validation_reports.items()
            },
            "research_findings": self.research_findings[-10:],
            "notes": self.system_notes[-20:],
        }
