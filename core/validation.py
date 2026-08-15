"""Validation suite: walk-forward, PBO, calibration and robustness.

The suite answers one question: *is the edge measured in-sample likely to
survive live trading?*  It combines four independent tests, each of which can
veto a candidate:

Walk-Forward Analysis (WFA)
    Re-optimises parameters on a rolling training window and measures the
    out-of-sample result.  ``efficiency`` compares OOS to IS performance.
Probability of Backtest Overfitting (PBO)
    Combinatorially Symmetric Cross Validation (Bailey, Borwein, Lopez de
    Prado, Zhu).  A PBO above ~0.5 means the selection procedure is no better
    than picking at random.
Calibration
    Compares the confidence the strategy attaches to a signal with the
    realised hit rate, reported as an Expected Calibration Error.
Robustness
    Parameter perturbation, cost sensitivity and volatility-regime analysis.
"""

from __future__ import annotations

import itertools
import json
import math
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional, Sequence

import numpy as np
import pandas as pd

from core.backtest import BacktestConfig, BacktestEngine, BacktestResult
from core.strategy import ParameterSpec, Strategy
from core.utils import annualisation_factor, deflated_sharpe_ratio
from utils.config import Config, get_config
from utils.exceptions import ValidationFailure
from utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class WalkForwardFold:
    """Result of a single walk-forward training/testing pair."""

    fold: int
    train_start: str
    train_end: str
    test_start: str
    test_end: str
    train_sharpe: float
    test_sharpe: float
    test_return: float
    test_trades: int
    best_params: Dict[str, Any] = field(default_factory=dict)


@dataclass
class WalkForwardReport:
    """Aggregated walk-forward analysis output."""

    folds: List[WalkForwardFold] = field(default_factory=list)
    efficiency: float = 0.0
    mean_test_sharpe: float = 0.0
    mean_train_sharpe: float = 0.0
    consistency: float = 0.0
    total_test_trades: int = 0

    def to_dict(self) -> Dict[str, Any]:
        """Serialise the report."""
        payload = asdict(self)
        payload["folds"] = [asdict(fold) for fold in self.folds]
        return payload


@dataclass
class PBOReport:
    """Probability of Backtest Overfitting summary.

    ``computed`` distinguishes "the test ran and found certain overfitting"
    from "the test was skipped": the default ``pbo`` of ``1.0`` is a fail-safe
    for gating, but consumers must not present it as a measurement.
    """

    pbo: float = 1.0
    computed: bool = False
    combinations: int = 0
    configurations: int = 0
    logits: List[float] = field(default_factory=list)
    best_config_params: Dict[str, Any] = field(default_factory=dict)
    performance_degradation: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        """Serialise the report."""
        return asdict(self)


@dataclass
class CalibrationReport:
    """Confidence calibration summary."""

    expected_calibration_error: float = 1.0
    brier_score: float = 1.0
    bins: List[Dict[str, float]] = field(default_factory=list)
    samples: int = 0

    def to_dict(self) -> Dict[str, Any]:
        """Serialise the report."""
        return asdict(self)


@dataclass
class RobustnessReport:
    """Parameter, cost and regime robustness summary."""

    parameter_stability: float = 0.0
    worst_perturbed_sharpe: float = 0.0
    median_perturbed_sharpe: float = 0.0
    cost_sensitivity: float = 1.0
    regime_sharpes: Dict[str, float] = field(default_factory=dict)
    survives_double_costs: bool = False

    def to_dict(self) -> Dict[str, Any]:
        """Serialise the report."""
        return asdict(self)


@dataclass
class ValidationReport:
    """Complete validation verdict for one strategy."""

    strategy_name: str
    strategy_id: str
    symbol: str
    timeframe: str
    baseline: Dict[str, Any] = field(default_factory=dict)
    walk_forward: WalkForwardReport = field(default_factory=WalkForwardReport)
    pbo: PBOReport = field(default_factory=PBOReport)
    calibration: CalibrationReport = field(default_factory=CalibrationReport)
    robustness: RobustnessReport = field(default_factory=RobustnessReport)
    deflated_sharpe: float = 0.0
    passed: bool = False
    score: float = 0.0
    reasons: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """Serialise the whole report for the API and persistence."""
        return {
            "strategy_name": self.strategy_name,
            "strategy_id": self.strategy_id,
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "baseline": self.baseline,
            "walk_forward": self.walk_forward.to_dict(),
            "pbo": self.pbo.to_dict(),
            "calibration": self.calibration.to_dict(),
            "robustness": self.robustness.to_dict(),
            "deflated_sharpe": self.deflated_sharpe,
            "passed": self.passed,
            "score": self.score,
            "reasons": self.reasons,
        }


def sample_parameters(
    strategy: Strategy, count: int, rng: Optional[np.random.Generator] = None
) -> List[Dict[str, Any]]:
    """Draw ``count`` random parameter sets from a strategy's search space."""
    generator = rng or np.random.default_rng(7)
    space: Sequence[ParameterSpec] = strategy.param_space
    if not space:
        return [dict(strategy.params)]

    def _key(params: Dict[str, Any]) -> str:
        """Hashable identity of a parameter set (values may be lists)."""
        return json.dumps(params, sort_keys=True, default=str)

    samples: List[Dict[str, Any]] = [dict(strategy.params)]
    seen = {_key(strategy.params)}
    attempts = 0
    while len(samples) < count and attempts < count * 10:
        attempts += 1
        candidate = dict(strategy.params)
        for spec in space:
            candidate[spec.name] = spec.sample(generator)
        key = _key(candidate)
        if key in seen:
            continue
        seen.add(key)
        samples.append(candidate)
    return samples


class WalkForwardAnalyzer:
    """Rolling train/test evaluation with in-sample parameter selection."""

    def __init__(
        self,
        engine: BacktestEngine,
        train_bars: int,
        test_bars: int,
        candidates: int = 12,
        min_folds: int = 3,
    ) -> None:
        """Initialise the analyzer.

        Args:
            engine: Backtest engine used for every evaluation.
            train_bars: Bars in each training window.
            test_bars: Bars in each testing window.
            candidates: Parameter sets evaluated per training window.
            min_folds: Minimum number of folds required for a valid result.
        """
        self.engine = engine
        self.train_bars = max(train_bars, 200)
        self.test_bars = max(test_bars, 50)
        self.candidates = max(candidates, 1)
        self.min_folds = max(min_folds, 1)

    def run(self, strategy: Strategy, df: pd.DataFrame) -> WalkForwardReport:
        """Execute the walk-forward analysis.

        Args:
            strategy: Strategy prototype (its params seed the search).
            df: Full OHLCV history.

        Returns:
            A :class:`WalkForwardReport`.
        """
        report = WalkForwardReport()
        total = len(df)
        window = self.train_bars + self.test_bars
        if total < window + self.test_bars:
            # Shrink the windows so short histories still produce folds.
            scale = max(total // (self.min_folds + 2), 100)
            self.train_bars = int(scale * 0.75)
            self.test_bars = max(int(scale * 0.25), 40)
            window = self.train_bars + self.test_bars
        if total < window:
            logger.warning("History too short for walk-forward", bars=total, needed=window)
            return report

        rng = np.random.default_rng(11)
        parameter_sets = sample_parameters(strategy, self.candidates, rng)

        fold_index = 0
        start = 0
        while start + window <= total:
            train = df.iloc[start : start + self.train_bars]
            test = df.iloc[start + self.train_bars : start + window]

            best_params: Dict[str, Any] = dict(strategy.params)
            best_sharpe = -np.inf
            for params in parameter_sets:
                candidate = strategy.with_params(**params)
                try:
                    result = self.engine.run(candidate, train)
                except Exception:
                    continue
                if result.metrics.trades < 3:
                    continue
                if result.metrics.sharpe > best_sharpe:
                    best_sharpe = result.metrics.sharpe
                    best_params = params

            if not np.isfinite(best_sharpe):
                start += self.test_bars
                continue

            try:
                oos = self.engine.run(strategy.with_params(**best_params), test)
            except Exception as exc:
                logger.warning("Walk-forward test window failed", error=str(exc))
                start += self.test_bars
                continue

            fold_index += 1
            report.folds.append(
                WalkForwardFold(
                    fold=fold_index,
                    train_start=str(train.index[0]),
                    train_end=str(train.index[-1]),
                    test_start=str(test.index[0]),
                    test_end=str(test.index[-1]),
                    train_sharpe=float(best_sharpe),
                    test_sharpe=float(oos.metrics.sharpe),
                    test_return=float(oos.metrics.total_return),
                    test_trades=int(oos.metrics.trades),
                    best_params=dict(best_params),
                )
            )
            start += self.test_bars

        if report.folds:
            train_sharpes = np.array([fold.train_sharpe for fold in report.folds])
            test_sharpes = np.array([fold.test_sharpe for fold in report.folds])
            report.mean_train_sharpe = float(np.mean(train_sharpes))
            report.mean_test_sharpe = float(np.mean(test_sharpes))
            denominator = float(np.mean(np.abs(train_sharpes)))
            report.efficiency = float(report.mean_test_sharpe / denominator) if denominator > 1e-9 else 0.0
            report.consistency = float(np.mean(test_sharpes > 0))
            report.total_test_trades = int(sum(fold.test_trades for fold in report.folds))
        return report


class PBOAnalyzer:
    """Combinatorially Symmetric Cross Validation estimate of overfitting."""

    def __init__(self, engine: BacktestEngine, partitions: int = 8, configurations: int = 16) -> None:
        """Initialise the analyzer.

        Args:
            engine: Backtest engine.
            partitions: Even number of contiguous data partitions (``S``).
            configurations: Number of parameter sets evaluated (``N``).
        """
        self.engine = engine
        self.partitions = partitions if partitions % 2 == 0 else partitions + 1
        self.configurations = max(configurations, 4)

    def run(self, strategy: Strategy, df: pd.DataFrame) -> PBOReport:
        """Estimate the probability of backtest overfitting."""
        report = PBOReport(configurations=0)
        rng = np.random.default_rng(23)
        parameter_sets = sample_parameters(strategy, self.configurations, rng)

        returns_matrix: List[np.ndarray] = []
        kept_params: List[Dict[str, Any]] = []
        for params in parameter_sets:
            try:
                result = self.engine.run(strategy.with_params(**params), df)
            except Exception:
                continue
            series = result.returns.to_numpy(dtype="float64")
            if series.size == 0 or not np.isfinite(series).all() or np.allclose(series, 0.0):
                continue
            returns_matrix.append(series)
            kept_params.append(params)

        if len(returns_matrix) < 4:
            logger.warning("Not enough configurations for PBO", configurations=len(returns_matrix))
            return report

        matrix = np.vstack(returns_matrix)  # shape (configs, observations)
        configs, observations = matrix.shape
        report.configurations = configs

        partitions = min(self.partitions, max(4, (observations // 50) * 2))
        if partitions % 2:
            partitions -= 1
        partitions = max(partitions, 4)
        chunk = observations // partitions
        if chunk < 10:
            logger.warning("Series too short for PBO partitioning", observations=observations)
            return report
        blocks = [matrix[:, index * chunk : (index + 1) * chunk] for index in range(partitions)]

        logits: List[float] = []
        degradations: List[float] = []
        half = partitions // 2
        for combination in itertools.combinations(range(partitions), half):
            in_sample_blocks = [blocks[index] for index in combination]
            out_blocks = [blocks[index] for index in range(partitions) if index not in combination]
            in_sample = np.concatenate(in_sample_blocks, axis=1)
            out_sample = np.concatenate(out_blocks, axis=1)

            is_scores = self._sharpe_rows(in_sample)
            oos_scores = self._sharpe_rows(out_sample)
            best = int(np.argmax(is_scores))
            ranks = np.argsort(np.argsort(oos_scores))  # 0 = worst
            relative_rank = (ranks[best] + 1) / (configs + 1)
            relative_rank = min(max(relative_rank, 1e-6), 1 - 1e-6)
            logits.append(float(math.log(relative_rank / (1 - relative_rank))))
            degradations.append(float(oos_scores[best] - is_scores[best]))

        if not logits:
            return report
        report.combinations = len(logits)
        report.logits = [round(value, 4) for value in logits[:200]]
        report.pbo = float(np.mean(np.array(logits) <= 0.0))
        report.computed = True
        report.performance_degradation = float(np.mean(degradations))
        overall = self._sharpe_rows(matrix)
        report.best_config_params = kept_params[int(np.argmax(overall))]
        return report

    @staticmethod
    def _sharpe_rows(matrix: np.ndarray) -> np.ndarray:
        """Return a per-row Sharpe-like score (mean over standard deviation)."""
        mean = matrix.mean(axis=1)
        std = matrix.std(axis=1, ddof=1)
        std[std < 1e-12] = np.inf
        return mean / std


class CalibrationChecker:
    """Compares signal confidence with realised outcomes."""

    def __init__(self, bins: int = 10) -> None:
        """Initialise with the number of reliability bins."""
        self.bins = max(bins, 2)

    def run(self, result: BacktestResult) -> CalibrationReport:
        """Compute the calibration report from a backtest result.

        Confidence is interpreted as the probability that a trade closes
        profitably.
        """
        report = CalibrationReport()
        trades = result.trades
        if len(trades) < 10:
            return report

        confidences = np.array([trade.confidence for trade in trades], dtype="float64")
        outcomes = np.array([1.0 if trade.pnl > 0 else 0.0 for trade in trades], dtype="float64")
        report.samples = len(trades)
        report.brier_score = float(np.mean((confidences - outcomes) ** 2))

        edges = np.linspace(0.0, 1.0, self.bins + 1)
        error = 0.0
        for index in range(self.bins):
            low, high = edges[index], edges[index + 1]
            mask = (confidences >= low) & (confidences < high if index < self.bins - 1 else confidences <= high)
            if not mask.any():
                continue
            predicted = float(confidences[mask].mean())
            observed = float(outcomes[mask].mean())
            weight = float(mask.sum()) / len(trades)
            error += weight * abs(predicted - observed)
            report.bins.append(
                {
                    "bin_low": round(float(low), 3),
                    "bin_high": round(float(high), 3),
                    "predicted": round(predicted, 4),
                    "observed": round(observed, 4),
                    "count": int(mask.sum()),
                }
            )
        report.expected_calibration_error = float(error)
        return report


class RobustnessTester:
    """Parameter perturbation, cost sensitivity and regime analysis."""

    def __init__(self, engine: BacktestEngine, perturbations: int = 16, magnitude: float = 0.2) -> None:
        """Initialise the tester."""
        self.engine = engine
        self.perturbations = max(perturbations, 4)
        self.magnitude = magnitude

    def run(self, strategy: Strategy, df: pd.DataFrame, baseline: BacktestResult) -> RobustnessReport:
        """Run every robustness test and aggregate the outcome."""
        report = RobustnessReport()
        rng = np.random.default_rng(31)

        sharpes: List[float] = []
        for _ in range(self.perturbations):
            params = dict(strategy.params)
            for spec in strategy.param_space:
                current = float(params.get(spec.name, spec.low))
                shift = current * rng.uniform(-self.magnitude, self.magnitude)
                params[spec.name] = spec.clip(current + shift)
            try:
                result = self.engine.run(strategy.with_params(**params), df)
            except Exception:
                continue
            sharpes.append(float(result.metrics.sharpe))

        if sharpes:
            array = np.array(sharpes)
            report.worst_perturbed_sharpe = float(array.min())
            report.median_perturbed_sharpe = float(np.median(array))
            spread = float(array.std(ddof=1)) if len(array) > 1 else 0.0
            reference = max(abs(baseline.metrics.sharpe), 0.25)
            report.parameter_stability = float(max(0.0, 1.0 - spread / reference))

        # Cost sensitivity: double commission and slippage.
        stressed_config = BacktestConfig(**{**self.engine.config.__dict__})
        stressed_config.commission = self.engine.config.commission * 2.0
        stressed_config.slippage = self.engine.config.slippage * 2.0
        try:
            stressed = BacktestEngine(stressed_config).run(strategy, df)
            baseline_sharpe = baseline.metrics.sharpe
            report.cost_sensitivity = float(
                (baseline_sharpe - stressed.metrics.sharpe) / max(abs(baseline_sharpe), 0.25)
            )
            report.survives_double_costs = bool(stressed.metrics.sharpe > 0)
        except Exception as exc:
            logger.warning("Cost sensitivity test failed", error=str(exc))

        # Volatility regime analysis.
        try:
            volatility = df["close"].pct_change().rolling(50, min_periods=20).std()
            tercile_low, tercile_high = volatility.quantile([1 / 3, 2 / 3])
            regimes = {
                "low_volatility": df[volatility <= tercile_low],
                "mid_volatility": df[(volatility > tercile_low) & (volatility <= tercile_high)],
                "high_volatility": df[volatility > tercile_high],
            }
            for label, subset in regimes.items():
                if len(subset) < 200:
                    continue
                regime_result = self.engine.run(strategy, subset)
                report.regime_sharpes[label] = round(float(regime_result.metrics.sharpe), 3)
        except Exception as exc:
            logger.warning("Regime analysis failed", error=str(exc))
        return report


class ValidationSuite:
    """Runs every validation test and issues a pass/fail verdict."""

    def __init__(self, config: Optional[Config] = None, engine: Optional[BacktestEngine] = None) -> None:
        """Initialise the suite from configuration."""
        self.config = config or get_config()
        self.engine = engine or BacktestEngine(BacktestConfig.from_config(self.config))
        self.thresholds = {
            "min_sharpe": self.config.get_float("validation.thresholds.min_sharpe", 0.5),
            "min_trades": self.config.get_int("validation.thresholds.min_trades", 30),
            "max_pbo": self.config.get_float("validation.thresholds.max_pbo", 0.5),
            "min_wfa_efficiency": self.config.get_float("validation.thresholds.min_wfa_efficiency", 0.4),
            "max_calibration_error": self.config.get_float("validation.thresholds.max_calibration_error", 0.15),
        }

    def run(self, strategy: Strategy, df: pd.DataFrame, quick: bool = False) -> ValidationReport:
        """Validate a strategy end to end.

        Args:
            strategy: Strategy to validate.
            df: Full OHLCV history.
            quick: Skip the expensive PBO/robustness passes (used by agents
                during candidate screening).

        Returns:
            A populated :class:`ValidationReport`.

        Raises:
            ValidationFailure: If the baseline backtest cannot be produced.
        """
        try:
            baseline = self.engine.run(strategy, df)
        except Exception as exc:
            raise ValidationFailure(
                "Baseline backtest failed", strategy=strategy.name, error=str(exc)
            ) from exc

        report = ValidationReport(
            strategy_name=strategy.name,
            strategy_id=strategy.strategy_id,
            symbol=strategy.symbol,
            timeframe=strategy.timeframe,
            baseline=baseline.to_dict(),
        )

        bars_per_month = int(annualisation_factor(strategy.timeframe) / 12)
        train_months = self.config.get_int("validation.walk_forward.train_months", 12)
        test_months = self.config.get_int("validation.walk_forward.test_months", 3)
        analyzer = WalkForwardAnalyzer(
            self.engine,
            train_bars=bars_per_month * train_months,
            test_bars=bars_per_month * test_months,
            candidates=6 if quick else 12,
            min_folds=self.config.get_int("validation.walk_forward.min_folds", 3),
        )
        report.walk_forward = analyzer.run(strategy, df)
        report.calibration = CalibrationChecker(
            self.config.get_int("validation.calibration.confidence_bins", 10)
        ).run(baseline)

        if not quick:
            report.pbo = PBOAnalyzer(
                self.engine,
                partitions=self.config.get_int("validation.pbo.partitions", 8),
                configurations=16,
            ).run(strategy, df)
            report.robustness = RobustnessTester(
                self.engine,
                perturbations=self.config.get_int("validation.robustness.perturbations", 16),
                magnitude=self.config.get_float("validation.robustness.perturbation_pct", 0.2),
            ).run(strategy, df, baseline)

        observations = max(len(baseline.equity_curve) - 1, 2)
        trials = max(report.pbo.configurations, 1)
        report.deflated_sharpe = deflated_sharpe_ratio(
            baseline.metrics.sharpe, trials, observations
        )
        self._decide(report, baseline, quick)
        logger.info(
            "Validation complete",
            strategy=strategy.name,
            symbol=strategy.symbol,
            passed=report.passed,
            score=round(report.score, 3),
            sharpe=round(baseline.metrics.sharpe, 3),
            pbo=round(report.pbo.pbo, 3) if report.pbo.computed else "not-computed",
        )
        return report

    def _decide(self, report: ValidationReport, baseline: BacktestResult, quick: bool) -> None:
        """Apply the acceptance thresholds and compute a composite score."""
        reasons: List[str] = []
        metrics = baseline.metrics

        if metrics.trades < self.thresholds["min_trades"]:
            reasons.append(
                f"Insufficient trades: {metrics.trades} < {self.thresholds['min_trades']}"
            )
        if metrics.sharpe < self.thresholds["min_sharpe"]:
            reasons.append(f"Sharpe {metrics.sharpe:.2f} below {self.thresholds['min_sharpe']:.2f}")
        if report.walk_forward.folds and report.walk_forward.efficiency < self.thresholds["min_wfa_efficiency"]:
            reasons.append(
                f"Walk-forward efficiency {report.walk_forward.efficiency:.2f} below "
                f"{self.thresholds['min_wfa_efficiency']:.2f}"
            )
        if not report.walk_forward.folds:
            reasons.append("Walk-forward analysis produced no folds")
        if not quick:
            if report.pbo.pbo > self.thresholds["max_pbo"]:
                reasons.append(f"PBO {report.pbo.pbo:.2f} above {self.thresholds['max_pbo']:.2f}")
            if not report.robustness.survives_double_costs:
                reasons.append("Edge disappears when transaction costs double")
        if report.calibration.samples >= 10 and (
            report.calibration.expected_calibration_error > self.thresholds["max_calibration_error"]
        ):
            reasons.append(
                f"Calibration error {report.calibration.expected_calibration_error:.2f} above "
                f"{self.thresholds['max_calibration_error']:.2f}"
            )

        report.reasons = reasons
        report.passed = not reasons
        report.score = self._score(report, baseline)

    @staticmethod
    def _score(report: ValidationReport, baseline: BacktestResult) -> float:
        """Blend the individual tests into a single ``[0, 1]`` quality score."""
        sharpe_component = min(max(baseline.metrics.sharpe / 2.0, 0.0), 1.0)
        wfa_component = min(max(report.walk_forward.efficiency, 0.0), 1.0)
        pbo_component = 1.0 - min(max(report.pbo.pbo, 0.0), 1.0)
        calibration_component = 1.0 - min(report.calibration.expected_calibration_error / 0.3, 1.0)
        robustness_component = min(max(report.robustness.parameter_stability, 0.0), 1.0)
        weights = (0.30, 0.25, 0.20, 0.10, 0.15)
        components = (
            sharpe_component,
            wfa_component,
            pbo_component,
            calibration_component,
            robustness_component,
        )
        return float(sum(weight * value for weight, value in zip(weights, components)))


def validate_strategy(
    strategy: Strategy, df: pd.DataFrame, config: Optional[Config] = None, quick: bool = False
) -> ValidationReport:
    """Convenience wrapper around :class:`ValidationSuite`."""
    return ValidationSuite(config).run(strategy, df, quick=quick)
