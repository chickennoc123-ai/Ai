"""
Config validation: reject any operator configuration that differs from the
frozen SC_SURPRISE_CONFIRMATION specification.

This is the Python-side counterpart to the MQL5 EA's ValidateFrozenConfig().
Both must independently refuse the same class of mismatch; this module is
what the replay harness and any future non-MT5 target (paper-trading
runner, monitoring dashboard, etc.) should import rather than re-deriving
the check.
"""
from dataclasses import dataclass
from typing import Dict

from ea_products.sc_surprise_confirmation.frozen_spec import (
    load_frozen_combinations, FrozenCombination, ENTRY_DELAY_SEC, IMPULSE_WINDOW_MIN,
)


class ConfigRejected(RuntimeError):
    """Raised when an operator-supplied config does not exactly match a frozen combination."""


@dataclass
class OperatorConfig:
    candidate_id: str
    symbol: str
    driver: str
    window_min: int
    entry_delay_sec: int = ENTRY_DELAY_SEC
    impulse_window_min: int = IMPULSE_WINDOW_MIN


def validate(config: OperatorConfig) -> FrozenCombination:
    """
    Return the matching FrozenCombination, or raise ConfigRejected.

    Every field must match exactly. There is no "closest match" or
    tolerance -- an operator who wants a different window, symbol, or
    driver is asking for an untested combination, which this validator's
    entire purpose is to refuse.
    """
    combos = {c.candidate_id: c for c in load_frozen_combinations()}
    if config.candidate_id not in combos:
        raise ConfigRejected(
            f"{config.candidate_id!r} is not one of the 6 frozen combinations: "
            f"{sorted(combos)}")
    c = combos[config.candidate_id]

    mismatches = []
    if config.symbol != c.symbol:
        mismatches.append(f"symbol: config={config.symbol!r} frozen={c.symbol!r}")
    if config.driver != c.driver:
        mismatches.append(f"driver: config={config.driver!r} frozen={c.driver!r}")
    if config.window_min != c.window_min:
        mismatches.append(f"window_min: config={config.window_min} frozen={c.window_min}")
    if config.entry_delay_sec != c.entry_delay_sec:
        mismatches.append(f"entry_delay_sec: config={config.entry_delay_sec} "
                          f"frozen={c.entry_delay_sec}")
    if config.impulse_window_min != c.impulse_window_min:
        mismatches.append(f"impulse_window_min: config={config.impulse_window_min} "
                          f"frozen={c.impulse_window_min}")

    if mismatches:
        raise ConfigRejected(
            f"config for {config.candidate_id!r} does not match its frozen specification:\n  "
            + "\n  ".join(mismatches))
    return c
