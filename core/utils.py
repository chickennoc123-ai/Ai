"""Instrument specifications and performance analytics.

This module is the single source of truth for contract sizes, pip values and
P&L conversion, plus the risk/return statistics used across the backtester,
the validation suite and the dashboard.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Mapping, Optional, Sequence

import numpy as np
import pandas as pd

from utils.helpers import bars_per_year, round_to_step, safe_float

TRADING_DAYS_PER_YEAR = 252


@dataclass(frozen=True)
class InstrumentSpec:
    """Static contract specification for a tradable symbol.

    Attributes:
        symbol: Broker symbol, e.g. ``"XAUUSD"``.
        digits: Number of decimals quoted by the broker.
        pip_size: Price increment representing one pip.
        contract_size: Units of base currency (or ounces) per 1.00 lot.
        min_lot / max_lot / lot_step: Volume constraints.
        typical_spread_pips: Average spread used by the simulator.
        commission_per_lot: Round-turn commission in account currency.
        swap_long / swap_short: Daily financing in account currency per lot.
        quote_currency: Currency the instrument is quoted in.
        inverse_quote: ``True`` when the account currency is the quote currency
            base (e.g. USDJPY), requiring division by price for USD conversion.
    """

    symbol: str
    digits: int
    pip_size: float
    contract_size: float
    min_lot: float = 0.01
    max_lot: float = 50.0
    lot_step: float = 0.01
    typical_spread_pips: float = 1.5
    commission_per_lot: float = 7.0
    swap_long: float = -2.5
    swap_short: float = -1.0
    quote_currency: str = "USD"
    inverse_quote: bool = False
    annual_volatility: float = 0.10
    category: str = "forex"

    @property
    def point(self) -> float:
        """Smallest quoted price increment."""
        return 10 ** (-self.digits)

    def normalize_price(self, price: float) -> float:
        """Round a price to the instrument's quoting precision."""
        return round(float(price), self.digits)

    def normalize_volume(self, volume: float) -> float:
        """Clamp and round a lot size to the broker's volume grid."""
        stepped = round_to_step(max(volume, 0.0), self.lot_step)
        if stepped < self.min_lot:
            return 0.0
        return round(min(stepped, self.max_lot), 2)

    def pip_value(self, price: float, lots: float = 1.0) -> float:
        """Return the account-currency value of one pip for ``lots``.

        Args:
            price: Current instrument price (needed for inverse quotes).
            lots: Position size in lots.
        """
        notional_pip = self.contract_size * self.pip_size * lots
        if self.inverse_quote:
            return notional_pip / max(price, 1e-9)
        return notional_pip

    def price_to_pips(self, price_delta: float) -> float:
        """Convert a price difference into pips."""
        return price_delta / self.pip_size

    def pips_to_price(self, pips: float) -> float:
        """Convert pips into a price difference."""
        return pips * self.pip_size


#: Contract specifications for the five supported instruments.
INSTRUMENTS: Dict[str, InstrumentSpec] = {
    "XAUUSD": InstrumentSpec(
        symbol="XAUUSD",
        digits=2,
        pip_size=0.1,
        contract_size=100.0,
        min_lot=0.01,
        max_lot=20.0,
        typical_spread_pips=3.0,
        commission_per_lot=0.0,
        swap_long=-6.5,
        swap_short=2.0,
        annual_volatility=0.16,
        category="metal",
    ),
    "EURUSD": InstrumentSpec(
        symbol="EURUSD",
        digits=5,
        pip_size=0.0001,
        contract_size=100_000.0,
        typical_spread_pips=1.6,
        commission_per_lot=0.0,
        swap_long=-7.0,
        swap_short=2.5,
        annual_volatility=0.07,
    ),
    "USDJPY": InstrumentSpec(
        symbol="USDJPY",
        digits=3,
        pip_size=0.01,
        contract_size=100_000.0,
        typical_spread_pips=1.8,
        commission_per_lot=0.0,
        swap_long=4.5,
        swap_short=-9.0,
        quote_currency="JPY",
        inverse_quote=True,
        annual_volatility=0.09,
    ),
    "GBPUSD": InstrumentSpec(
        symbol="GBPUSD",
        digits=5,
        pip_size=0.0001,
        contract_size=100_000.0,
        typical_spread_pips=2.0,
        commission_per_lot=0.0,
        swap_long=-6.0,
        swap_short=1.5,
        annual_volatility=0.09,
    ),
    "AUDUSD": InstrumentSpec(
        symbol="AUDUSD",
        digits=5,
        pip_size=0.0001,
        contract_size=100_000.0,
        typical_spread_pips=1.8,
        commission_per_lot=0.0,
        swap_long=-3.0,
        swap_short=0.5,
        annual_volatility=0.08,
    ),
}

#: Reference prices used to seed the simulator and sanity-check quotes.
REFERENCE_PRICES: Dict[str, float] = {
    "XAUUSD": 2035.50,
    "EURUSD": 1.08750,
    "USDJPY": 148.250,
    "GBPUSD": 1.26400,
    "AUDUSD": 0.65800,
}


def get_instrument(symbol: str) -> InstrumentSpec:
    """Return the :class:`InstrumentSpec` for ``symbol``.

    Raises:
        KeyError: If the symbol is not part of the supported universe.
    """
    key = symbol.strip().upper()
    if key not in INSTRUMENTS:
        raise KeyError(f"Unknown instrument: {symbol}")
    return INSTRUMENTS[key]


def supported_symbols() -> List[str]:
    """Return the list of supported symbols."""
    return list(INSTRUMENTS)


def position_pnl(
    spec: InstrumentSpec,
    direction: int,
    entry_price: float,
    exit_price: float,
    lots: float,
) -> float:
    """Compute gross P&L in account currency for a closed position.

    Args:
        spec: Instrument specification.
        direction: ``1`` for long, ``-1`` for short.
        entry_price: Fill price at entry.
        exit_price: Fill price at exit.
        lots: Position size in lots.
    """
    price_delta = (exit_price - entry_price) * (1 if direction >= 0 else -1)
    gross = price_delta * spec.contract_size * lots
    if spec.inverse_quote:
        gross /= max(exit_price, 1e-9)
    return gross


def required_margin(spec: InstrumentSpec, price: float, lots: float, leverage: float) -> float:
    """Return the margin required to hold ``lots`` at ``price``."""
    notional = spec.contract_size * lots * price
    if spec.inverse_quote:
        notional /= max(price, 1e-9)
    return notional / max(leverage, 1.0)


def notional_value(spec: InstrumentSpec, price: float, lots: float) -> float:
    """Return the account-currency notional exposure of a position."""
    notional = spec.contract_size * lots * price
    if spec.inverse_quote:
        notional /= max(price, 1e-9)
    return notional


def lots_for_risk(
    spec: InstrumentSpec,
    capital: float,
    risk_fraction: float,
    stop_distance_price: float,
    price: float,
) -> float:
    """Size a position so a stop-out costs ``risk_fraction`` of capital.

    Args:
        spec: Instrument specification.
        capital: Account equity available for risk.
        risk_fraction: Fraction of capital risked (e.g. ``0.01``).
        stop_distance_price: Distance between entry and stop in price units.
        price: Current price (used for inverse-quote conversion).

    Returns:
        A broker-normalised lot size, possibly ``0.0`` when the risk budget is
        too small for the minimum lot.
    """
    if stop_distance_price <= 0 or capital <= 0 or risk_fraction <= 0:
        return 0.0
    risk_amount = capital * risk_fraction
    loss_per_lot = abs(position_pnl(spec, 1, price, price - stop_distance_price, 1.0))
    if loss_per_lot <= 0:
        return 0.0
    return spec.normalize_volume(risk_amount / loss_per_lot)


# ---------------------------------------------------------------------------
# Performance analytics
# ---------------------------------------------------------------------------


@dataclass
class PerformanceMetrics:
    """Container for the standard risk/return statistics of a track record."""

    total_return: float = 0.0
    cagr: float = 0.0
    sharpe: float = 0.0
    sortino: float = 0.0
    calmar: float = 0.0
    max_drawdown: float = 0.0
    max_drawdown_duration: int = 0
    volatility: float = 0.0
    win_rate: float = 0.0
    profit_factor: float = 0.0
    expectancy: float = 0.0
    payoff_ratio: float = 0.0
    trades: int = 0
    wins: int = 0
    losses: int = 0
    avg_win: float = 0.0
    avg_loss: float = 0.0
    largest_win: float = 0.0
    largest_loss: float = 0.0
    exposure: float = 0.0
    turnover: float = 0.0
    recovery_factor: float = 0.0
    ulcer_index: float = 0.0
    tail_ratio: float = 0.0
    net_profit: float = 0.0
    gross_profit: float = 0.0
    gross_loss: float = 0.0
    commission_paid: float = 0.0
    final_equity: float = 0.0
    extras: Dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, float]:
        """Return a flat dictionary representation."""
        payload = {
            key: value for key, value in self.__dict__.items() if key != "extras"
        }
        payload.update(self.extras)
        return payload


def to_returns(equity: Sequence[float] | pd.Series) -> pd.Series:
    """Convert an equity curve into simple period returns."""
    series = pd.Series(equity, dtype="float64").replace([np.inf, -np.inf], np.nan).dropna()
    if len(series) < 2:
        return pd.Series(dtype="float64")
    return series.pct_change().dropna()


def sharpe_ratio(returns: pd.Series, periods_per_year: float = TRADING_DAYS_PER_YEAR, risk_free: float = 0.0) -> float:
    """Annualised Sharpe ratio of a return series."""
    if returns is None or len(returns) < 2:
        return 0.0
    excess = returns - risk_free / periods_per_year
    std = float(excess.std(ddof=1))
    if std <= 1e-12:
        return 0.0
    return float(excess.mean() / std * math.sqrt(periods_per_year))


def sortino_ratio(returns: pd.Series, periods_per_year: float = TRADING_DAYS_PER_YEAR, target: float = 0.0) -> float:
    """Annualised Sortino ratio (downside deviation denominator)."""
    if returns is None or len(returns) < 2:
        return 0.0
    downside = returns[returns < target]
    if len(downside) == 0:
        return 0.0
    downside_dev = float(np.sqrt(np.mean(np.square(downside - target))))
    if downside_dev <= 1e-12:
        return 0.0
    return float((returns.mean() - target) / downside_dev * math.sqrt(periods_per_year))


def max_drawdown(equity: Sequence[float] | pd.Series) -> float:
    """Return the maximum peak-to-trough drawdown as a positive fraction."""
    series = pd.Series(equity, dtype="float64")
    if series.empty:
        return 0.0
    running_max = series.cummax().replace(0, np.nan)
    drawdown = (series - running_max) / running_max
    value = float(drawdown.min()) if not drawdown.isna().all() else 0.0
    return abs(min(value, 0.0))


def drawdown_series(equity: Sequence[float] | pd.Series) -> pd.Series:
    """Return the drawdown series (negative fractions) for an equity curve."""
    series = pd.Series(equity, dtype="float64")
    if series.empty:
        return series
    running_max = series.cummax().replace(0, np.nan)
    return ((series - running_max) / running_max).fillna(0.0)


def max_drawdown_duration(equity: Sequence[float] | pd.Series) -> int:
    """Return the longest number of periods spent below a previous peak."""
    series = pd.Series(equity, dtype="float64")
    if series.empty:
        return 0
    peak = -np.inf
    longest = 0
    current = 0
    for value in series:
        if value >= peak:
            peak = value
            current = 0
        else:
            current += 1
            longest = max(longest, current)
    return int(longest)


def ulcer_index(equity: Sequence[float] | pd.Series) -> float:
    """Return the Ulcer Index, a depth-and-duration aware drawdown measure."""
    dd = drawdown_series(equity)
    if dd.empty:
        return 0.0
    return float(np.sqrt(np.mean(np.square(dd * 100.0))))


def calmar_ratio(cagr: float, mdd: float) -> float:
    """Return the Calmar ratio (CAGR over max drawdown)."""
    if mdd <= 1e-9:
        return 0.0
    return cagr / mdd


def tail_ratio(returns: pd.Series) -> float:
    """Ratio of the 95th percentile gain to the 5th percentile loss."""
    if returns is None or len(returns) < 20:
        return 0.0
    right = float(np.percentile(returns, 95))
    left = abs(float(np.percentile(returns, 5)))
    if left <= 1e-12:
        return 0.0
    return right / left


def value_at_risk(returns: pd.Series, confidence: float = 0.99) -> float:
    """Historical Value at Risk expressed as a positive fraction."""
    if returns is None or len(returns) < 5:
        return 0.0
    quantile = float(np.percentile(returns, (1 - confidence) * 100))
    return abs(min(quantile, 0.0))


def conditional_value_at_risk(returns: pd.Series, confidence: float = 0.99) -> float:
    """Expected shortfall beyond the VaR threshold, as a positive fraction."""
    if returns is None or len(returns) < 5:
        return 0.0
    threshold = float(np.percentile(returns, (1 - confidence) * 100))
    tail = returns[returns <= threshold]
    if tail.empty:
        return abs(min(threshold, 0.0))
    return abs(min(float(tail.mean()), 0.0))


def deflated_sharpe_ratio(sharpe: float, trials: int, observations: int, skew: float = 0.0, kurtosis: float = 3.0) -> float:
    """Approximate the Deflated Sharpe Ratio (Bailey & Lopez de Prado).

    Args:
        sharpe: Observed (annualised) Sharpe ratio.
        trials: Number of independent configurations tried.
        observations: Number of return observations.
        skew: Skewness of the return distribution.
        kurtosis: Kurtosis of the return distribution.

    Returns:
        Probability in ``[0, 1]`` that the observed Sharpe exceeds the expected
        maximum Sharpe obtainable by chance across ``trials``.
    """
    if observations < 10 or trials < 1:
        return 0.0
    euler_mascheroni = 0.5772156649
    trials = max(trials, 2)
    # Expected maximum Sharpe under the null of zero true skill.
    z_1 = _norm_ppf(1 - 1.0 / trials)
    z_2 = _norm_ppf(1 - 1.0 / (trials * math.e))
    expected_max = (1 - euler_mascheroni) * z_1 + euler_mascheroni * z_2
    denominator = math.sqrt(
        max(1e-12, 1 - skew * sharpe + (kurtosis - 1) / 4.0 * sharpe**2)
    )
    statistic = (sharpe - expected_max) * math.sqrt(observations - 1) / denominator
    return float(_norm_cdf(statistic))


def _norm_cdf(x: float) -> float:
    """Standard normal CDF via the error function."""
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _norm_ppf(p: float) -> float:
    """Approximate inverse standard normal CDF (Acklam's algorithm)."""
    p = min(max(p, 1e-9), 1 - 1e-9)
    a = [-3.969683028665376e01, 2.209460984245205e02, -2.759285104469687e02,
         1.383577518672690e02, -3.066479806614716e01, 2.506628277459239e00]
    b = [-5.447609879822406e01, 1.615858368580409e02, -1.556989798598866e02,
         6.680131188771972e01, -1.328068155288572e01]
    c = [-7.784894002430293e-03, -3.223964580411365e-01, -2.400758277161838e00,
         -2.549732539343734e00, 4.374664141464968e00, 2.938163982698783e00]
    d = [7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e00,
         3.754408661907416e00]
    plow, phigh = 0.02425, 1 - 0.02425
    if p < plow:
        q = math.sqrt(-2 * math.log(p))
        return (((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / (
            (((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1
        )
    if p > phigh:
        q = math.sqrt(-2 * math.log(1 - p))
        return -(((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / (
            (((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1
        )
    q = p - 0.5
    r = q * q
    return (((((a[0] * r + a[1]) * r + a[2]) * r + a[3]) * r + a[4]) * r + a[5]) * q / (
        ((((b[0] * r + b[1]) * r + b[2]) * r + b[3]) * r + b[4]) * r + 1
    )


def compute_metrics(
    equity: Sequence[float] | pd.Series,
    trade_pnls: Optional[Sequence[float]] = None,
    periods_per_year: float = TRADING_DAYS_PER_YEAR,
    initial_capital: Optional[float] = None,
    extras: Optional[Mapping[str, float]] = None,
) -> PerformanceMetrics:
    """Compute the full metric set for an equity curve and trade list.

    Args:
        equity: Equity curve samples (one per bar or per trade).
        trade_pnls: Realised P&L per closed trade.
        periods_per_year: Annualisation factor matching the equity sampling.
        initial_capital: Starting capital; inferred from the curve when omitted.
        extras: Additional metrics merged into the result.

    Returns:
        A populated :class:`PerformanceMetrics`.
    """
    series = pd.Series(equity, dtype="float64").replace([np.inf, -np.inf], np.nan).dropna()
    metrics = PerformanceMetrics()
    if extras:
        metrics.extras.update({key: safe_float(value) for key, value in extras.items()})
    if series.empty:
        return metrics

    start = float(initial_capital if initial_capital is not None else series.iloc[0])
    end = float(series.iloc[-1])
    metrics.final_equity = end
    metrics.total_return = (end / start - 1.0) if start else 0.0

    returns = to_returns(series)
    periods = max(len(series) - 1, 1)
    years = periods / periods_per_year if periods_per_year else 0.0
    if years > 0 and start > 0 and end > 0:
        metrics.cagr = (end / start) ** (1.0 / years) - 1.0
    metrics.volatility = float(returns.std(ddof=1) * math.sqrt(periods_per_year)) if len(returns) > 1 else 0.0
    metrics.sharpe = sharpe_ratio(returns, periods_per_year)
    metrics.sortino = sortino_ratio(returns, periods_per_year)
    metrics.max_drawdown = max_drawdown(series)
    metrics.max_drawdown_duration = max_drawdown_duration(series)
    metrics.calmar = calmar_ratio(metrics.cagr, metrics.max_drawdown)
    metrics.ulcer_index = ulcer_index(series)
    metrics.tail_ratio = tail_ratio(returns)
    metrics.net_profit = end - start
    if metrics.max_drawdown > 0 and start > 0:
        metrics.recovery_factor = metrics.net_profit / (metrics.max_drawdown * start)

    pnls = [safe_float(item) for item in (trade_pnls or [])]
    if pnls:
        wins = [value for value in pnls if value > 0]
        losses = [value for value in pnls if value < 0]
        metrics.trades = len(pnls)
        metrics.wins = len(wins)
        metrics.losses = len(losses)
        metrics.win_rate = len(wins) / len(pnls)
        metrics.gross_profit = float(sum(wins))
        metrics.gross_loss = abs(float(sum(losses)))
        metrics.profit_factor = (
            metrics.gross_profit / metrics.gross_loss if metrics.gross_loss > 1e-9 else float(len(wins) > 0) * 99.0
        )
        metrics.avg_win = float(np.mean(wins)) if wins else 0.0
        metrics.avg_loss = float(np.mean(losses)) if losses else 0.0
        metrics.largest_win = float(max(wins)) if wins else 0.0
        metrics.largest_loss = float(min(losses)) if losses else 0.0
        metrics.expectancy = float(np.mean(pnls))
        metrics.payoff_ratio = abs(metrics.avg_win / metrics.avg_loss) if metrics.avg_loss else 0.0
    return metrics


def annualisation_factor(timeframe: str) -> float:
    """Return the annualisation factor for bar-sampled returns."""
    return bars_per_year(timeframe)


def correlation_matrix(returns_by_key: Mapping[str, Sequence[float]]) -> pd.DataFrame:
    """Build a correlation matrix from unequal-length return series."""
    frame = pd.DataFrame({key: pd.Series(list(values), dtype="float64") for key, values in returns_by_key.items()})
    if frame.empty or frame.shape[1] < 2:
        return pd.DataFrame(np.eye(max(frame.shape[1], 1)), index=frame.columns, columns=frame.columns)
    return frame.corr().fillna(0.0)


def summarize(metrics: PerformanceMetrics, keys: Optional[Iterable[str]] = None) -> Dict[str, float]:
    """Return a compact subset of metrics for logging and dashboards."""
    default_keys = (
        "sharpe", "sortino", "calmar", "max_drawdown", "win_rate",
        "profit_factor", "trades", "total_return", "net_profit",
    )
    payload = metrics.to_dict()
    return {key: payload.get(key, 0.0) for key in (keys or default_keys)}
