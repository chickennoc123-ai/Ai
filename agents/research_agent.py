"""Research Agent: discovers and evolves trading strategies.

Two generators feed one funnel:

* **Evolutionary search** - mutates and recombines the parameters of the
  registered strategies, scoring each candidate with a quick validation pass.
* **Code synthesis** - writes brand new strategy classes, either from local
  templates (offline) or from an LLM when one is configured.

Every generated file passes an AST allow-list check and a smoke backtest before
it is written to :mod:`strategies.ai_generated`, so a malformed or hostile
generation can never be imported.
"""

from __future__ import annotations

import ast
import importlib
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from agents.base_agent import BaseAgent
from agents.llm import LLMClient, create_llm_client
from agents.message_bus import Message, MessageType
from core.backtest import BacktestConfig, BacktestEngine
from core.strategy import Strategy
from core.strategy_registry import available_strategies, create_strategy, load_strategies
from core.validation import ValidationSuite, sample_parameters
from utils.helpers import new_id, utcnow

GENERATED_DIR = Path("strategies/ai_generated")

#: Modules a generated strategy may import.
ALLOWED_IMPORTS = {
    "numpy",
    "pandas",
    "core.indicators",
    "core.strategy",
    "core.strategy_registry",
    "strategies.base_strategy",
    "typing",
    "__future__",
}

#: Names a generated strategy may never reference.
FORBIDDEN_NAMES = {
    "eval", "exec", "compile", "open", "__import__", "input", "breakpoint",
    "globals", "locals", "vars", "getattr", "setattr", "delattr", "memoryview",
}

#: Templates used by the offline synthesiser.
CODE_TEMPLATES: Dict[str, str] = {
    "oscillator_reversion": '''"""Auto-generated oscillator reversion strategy ({tag})."""

from __future__ import annotations

from typing import Any, ClassVar, Dict

import pandas as pd

from core.indicators import {indicator_import}
from core.strategy_registry import register_strategy
from strategies.base_strategy import BaseStrategy


@register_strategy
class {class_name}(BaseStrategy):
    """Fades {indicator} extremes and exits at the neutral level."""

    name: ClassVar[str] = "{strategy_name}"
    category: ClassVar[str] = "mean_reversion"
    description: ClassVar[str] = "Generated {indicator} reversion ({tag})"
    generated: ClassVar[bool] = True
    default_params: ClassVar[Dict[str, Any]] = {{
        "period": {period},
        "lower": {lower},
        "upper": {upper},
        "sl_atr": {sl_atr},
        "tp_atr": {tp_atr},
    }}

    def compute_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        """Generate reversion positions."""
        values = {indicator_call}
        lower = float(self.params["lower"])
        upper = float(self.params["upper"])
        midpoint = (lower + upper) / 2.0

        raw = pd.Series(0, index=df.index, dtype="int8")
        raw[values <= lower] = 1
        raw[values >= upper] = -1
        held = raw.replace(0, float("nan")).ffill().fillna(0).astype("int8")
        exit_long = (held > 0) & (values >= midpoint)
        exit_short = (held < 0) & (values <= midpoint)
        position = held.where(~(exit_long | exit_short).fillna(False), 0).astype("int8")

        confidence = self.scale_confidence((values - midpoint).abs(), 0.0, (upper - lower))
        return self.build_frame(df, position, confidence)
''',
    "dual_average": '''"""Auto-generated dual moving average strategy ({tag})."""

from __future__ import annotations

from typing import Any, ClassVar, Dict

import pandas as pd

from core.indicators import ema, sma
from core.strategy_registry import register_strategy
from strategies.base_strategy import BaseStrategy


@register_strategy
class {class_name}(BaseStrategy):
    """Trades the spread between a fast and a slow average of the close."""

    name: ClassVar[str] = "{strategy_name}"
    category: ClassVar[str] = "trend_following"
    description: ClassVar[str] = "Generated dual average crossover ({tag})"
    generated: ClassVar[bool] = True
    default_params: ClassVar[Dict[str, Any]] = {{
        "fast": {fast},
        "slow": {slow},
        "threshold_atr": {threshold_atr},
        "sl_atr": {sl_atr},
        "tp_atr": {tp_atr},
    }}

    def compute_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        """Generate crossover positions filtered by an ATR threshold."""
        close = df["close"]
        fast = {average}(close, int(self.params["fast"]))
        slow = {average}(close, max(int(self.params["slow"]), int(self.params["fast"]) + 1))
        atr_values = self.atr_series(df)
        spread = fast - slow
        threshold = float(self.params["threshold_atr"]) * atr_values

        position = pd.Series(0, index=df.index, dtype="int8")
        position[spread > threshold] = 1
        position[spread < -threshold] = -1

        confidence = self.scale_confidence(spread.abs() / atr_values.replace(0.0, float("nan")), 0.0, 3.0)
        return self.build_frame(df, position, confidence)
''',
    "channel_breakout": '''"""Auto-generated channel breakout strategy ({tag})."""

from __future__ import annotations

from typing import Any, ClassVar, Dict

import pandas as pd

from core.indicators import donchian_channel
from core.strategy_registry import register_strategy
from strategies.base_strategy import BaseStrategy


@register_strategy
class {class_name}(BaseStrategy):
    """Breaks out of a rolling price channel and trails with a shorter one."""

    name: ClassVar[str] = "{strategy_name}"
    category: ClassVar[str] = "volatility"
    description: ClassVar[str] = "Generated channel breakout ({tag})"
    generated: ClassVar[bool] = True
    default_params: ClassVar[Dict[str, Any]] = {{
        "entry_period": {entry_period},
        "exit_period": {exit_period},
        "sl_atr": {sl_atr},
        "tp_atr": {tp_atr},
    }}

    def compute_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        """Generate breakout positions."""
        high, low, close = df["high"], df["low"], df["close"]
        entry_upper, _, entry_lower = donchian_channel(high, low, int(self.params["entry_period"]))
        exit_upper, _, exit_lower = donchian_channel(high, low, max(int(self.params["exit_period"]), 2))
        entry_upper, entry_lower = entry_upper.shift(1), entry_lower.shift(1)
        exit_upper, exit_lower = exit_upper.shift(1), exit_lower.shift(1)

        raw = pd.Series(0, index=df.index, dtype="int8")
        raw[close >= entry_upper] = 1
        raw[close <= entry_lower] = -1
        held = raw.replace(0, float("nan")).ffill().fillna(0).astype("int8")
        exit_long = (held > 0) & (close <= exit_lower)
        exit_short = (held < 0) & (close >= exit_upper)
        position = held.where(~(exit_long | exit_short).fillna(False), 0).astype("int8")

        return self.build_frame(df, position)
''',
}

LLM_SYSTEM_PROMPT = """You are a quantitative developer writing Python trading strategies for the
EA Factory Pro platform. Reply with a single Python module and nothing else."""

LLM_USER_PROMPT = """Write one strategy class for the EA Factory Pro platform.

Hard requirements:
- Subclass `BaseStrategy` imported from `strategies.base_strategy`.
- Decorate the class with `@register_strategy` from `core.strategy_registry`.
- Set the class variables `name`, `category`, `description`, `generated = True`
  and `default_params`.
- Implement `compute_signals(self, df: pd.DataFrame) -> pd.DataFrame` and return
  `self.build_frame(df, position, confidence)` where `position` holds the desired
  position per bar in {{-1, 0, 1}}.
- Only import from: pandas, numpy, typing, core.indicators, core.strategy_registry,
  strategies.base_strategy.
- No file, network or process access. No eval/exec.

Context:
- Symbol: {symbol}, timeframe: {timeframe}
- Available indicators: {indicators}
- Idea to implement: {idea}
- Class name must be `{class_name}` and `name` must be `"{strategy_name}"`.
"""

STRATEGY_IDEAS = [
    "combine a volatility filter with a momentum trigger so trades only fire in expanding ranges",
    "trade pullbacks to a moving average inside an established trend",
    "fade the first hour range breakout when volume confirmation is missing",
    "use the difference between fast and slow RSI as a trend proxy",
    "enter on ATR expansion after a multi-bar contraction (squeeze release)",
    "trade divergences between price highs and an oscillator",
]


class CodeValidator:
    """AST allow-list validation for generated strategy code."""

    def __init__(
        self,
        allowed_imports: Optional[set[str]] = None,
        forbidden_names: Optional[set[str]] = None,
    ) -> None:
        """Initialise the validator with optional custom rules."""
        self.allowed_imports = allowed_imports or ALLOWED_IMPORTS
        self.forbidden_names = forbidden_names or FORBIDDEN_NAMES

    def validate(self, code: str) -> Tuple[bool, List[str]]:
        """Check a code string.

        Args:
            code: Python source of the generated module.

        Returns:
            Tuple of ``(is_valid, problems)``.
        """
        problems: List[str] = []
        try:
            tree = ast.parse(code)
        except SyntaxError as exc:
            return False, [f"Syntax error: {exc}"]

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.split(".")[0] not in {item.split(".")[0] for item in self.allowed_imports}:
                        problems.append(f"Disallowed import: {alias.name}")
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                if module not in self.allowed_imports and module.split(".")[0] not in {
                    item.split(".")[0] for item in self.allowed_imports
                }:
                    problems.append(f"Disallowed import from: {module}")
            elif isinstance(node, ast.Name) and node.id in self.forbidden_names:
                problems.append(f"Forbidden name: {node.id}")
            elif isinstance(node, ast.Attribute) and node.attr.startswith("__"):
                problems.append(f"Dunder attribute access: {node.attr}")

        if "register_strategy" not in code:
            problems.append("Missing @register_strategy decorator")
        if "compute_signals" not in code:
            problems.append("Missing compute_signals method")
        return not problems, problems


class ResearchAgent(BaseAgent):
    """Generates, evaluates and publishes new strategy candidates."""

    subscriptions = [MessageType.META_FEEDBACK, MessageType.COMMAND]

    def __init__(self, **kwargs: Any) -> None:
        """Initialise the research agent."""
        super().__init__("research", **kwargs)
        self.max_candidates = self.settings.get_int("max_candidates", 24)
        self.survivors = self.settings.get_int("survivors", 6)
        self.mutation_rate = self.settings.get_float("mutation_rate", 0.35)
        self.symbols: List[str] = list(self.config.get("broker.xmtrading.symbols", ["EURUSD"]))
        self.timeframe = str(self.config.get("agents.analysis.timeframe", "H1"))
        self.llm: Optional[LLMClient] = None
        self.engine = BacktestEngine(BacktestConfig.from_config(self.config))
        self.suite = ValidationSuite(self.config, self.engine)
        self.validator = CodeValidator()
        self.generation = 0
        self.population: List[Dict[str, Any]] = []
        self.hall_of_fame: List[Dict[str, Any]] = []
        self.generated_files: List[str] = []
        self._rng = np.random.default_rng(97)

    # -- lifecycle -----------------------------------------------------------
    async def initialize(self) -> bool:
        """Load the strategy registry and the LLM client."""
        load_strategies()
        self.llm = create_llm_client(self.config)
        GENERATED_DIR.mkdir(parents=True, exist_ok=True)
        self.logger.info(
            "Research agent ready",
            strategies=len(available_strategies()),
            llm_provider=self.llm.provider,
        )
        return True

    async def shutdown(self) -> None:
        """Close the LLM client."""
        if self.llm is not None:
            await self.llm.close()

    async def execute_cycle(self) -> None:
        """Run one generation of the research pipeline."""
        self.generation += 1
        data_manager = self.require_service("data_manager")
        symbol = str(self._rng.choice(self.symbols))
        df = await data_manager.get_ohlcv(symbol, self.timeframe, self.config.get_int("data.history_bars", 5000))

        candidates = self._build_population(symbol)
        scored = await self._evaluate_population(candidates, df)
        survivors = scored[: self.survivors]
        self.population = survivors

        best = survivors[0] if survivors else None
        if best is not None:
            self.hall_of_fame.append(best)
            self.hall_of_fame.sort(key=lambda item: item["score"], reverse=True)
            self.hall_of_fame = self.hall_of_fame[:20]

        synthesised = await self._synthesize_strategy(symbol)

        await self.publish(
            MessageType.RESEARCH_FINDING,
            {
                "generation": self.generation,
                "symbol": symbol,
                "timeframe": self.timeframe,
                "evaluated": len(scored),
                "survivors": [self._describe(item) for item in survivors],
                "best": self._describe(best) if best else None,
                "synthesised": synthesised,
                "timestamp": utcnow().isoformat(),
            },
        )
        self.logger.info(
            "Research generation complete",
            generation=self.generation,
            symbol=symbol,
            evaluated=len(scored),
            best_score=round(best["score"], 3) if best else 0.0,
        )

    async def process(self, message: Message) -> Optional[Message]:
        """React to meta feedback and manual commands."""
        if message.message_type is MessageType.META_FEEDBACK:
            adjustment = message.payload.get("research", {})
            if "mutation_rate" in adjustment:
                self.mutation_rate = float(adjustment["mutation_rate"])
                self.logger.info("Mutation rate adjusted by meta agent", value=self.mutation_rate)
            if "max_candidates" in adjustment:
                self.max_candidates = int(adjustment["max_candidates"])
        elif message.message_type is MessageType.COMMAND:
            if message.payload.get("command") == "research_now":
                await self.execute_cycle()
        return None

    # -- evolutionary search -------------------------------------------------
    def _build_population(self, symbol: str) -> List[Strategy]:
        """Build the next generation of candidate strategies."""
        population: List[Strategy] = []
        names = available_strategies()
        if not names:
            return population

        # Elites carried over from the previous generation.
        for item in self.population[: max(self.survivors // 2, 1)]:
            try:
                population.append(create_strategy(item["strategy"], symbol, self.timeframe, item["params"]))
            except Exception as exc:  # noqa: BLE001
                self.logger.debug("Could not revive elite", error=str(exc))

        # Mutations of the elites.
        for item in list(self.population):
            if len(population) >= self.max_candidates:
                break
            try:
                base = create_strategy(item["strategy"], symbol, self.timeframe, item["params"])
                population.append(self._mutate(base))
            except Exception as exc:  # noqa: BLE001
                self.logger.debug("Mutation failed", error=str(exc))

        # Random exploration fills the rest of the population.
        while len(population) < self.max_candidates:
            name = str(self._rng.choice(names))
            try:
                prototype = create_strategy(name, symbol, self.timeframe)
            except Exception:  # noqa: BLE001
                continue
            params = sample_parameters(prototype, 2, self._rng)[-1]
            population.append(prototype.with_params(**params))
        return population

    def _mutate(self, strategy: Strategy) -> Strategy:
        """Perturb a subset of a strategy's parameters."""
        params = dict(strategy.params)
        for spec in strategy.param_space:
            if self._rng.random() > self.mutation_rate:
                continue
            current = float(params.get(spec.name, spec.low))
            span = (spec.high - spec.low) * 0.25
            params[spec.name] = spec.clip(current + float(self._rng.normal(0.0, span)))
        return strategy.with_params(**params)

    async def _evaluate_population(self, population: List[Strategy], df: Any) -> List[Dict[str, Any]]:
        """Score every candidate with a quick validation pass."""
        scored: List[Dict[str, Any]] = []
        for candidate in population:
            try:
                report = self.suite.run(candidate, df, quick=True)
            except Exception as exc:  # noqa: BLE001 - a bad candidate must not stop research
                self.logger.debug("Candidate evaluation failed", strategy=candidate.name, error=str(exc))
                continue
            metrics = report.baseline.get("metrics", {})
            scored.append(
                {
                    "strategy": candidate.name,
                    "strategy_id": candidate.strategy_id,
                    "symbol": candidate.symbol,
                    "timeframe": candidate.timeframe,
                    "params": dict(candidate.params),
                    "score": report.score,
                    "sharpe": float(metrics.get("sharpe", 0.0)),
                    "trades": int(metrics.get("trades", 0)),
                    "max_drawdown": float(metrics.get("max_drawdown", 0.0)),
                    "wfa_efficiency": report.walk_forward.efficiency,
                    "passed_quick_gate": report.passed,
                }
            )
        scored.sort(key=lambda item: item["score"], reverse=True)
        return scored

    @staticmethod
    def _describe(item: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        """Return a compact description of a scored candidate."""
        if not item:
            return {}
        return {
            "strategy": item["strategy"],
            "symbol": item["symbol"],
            "score": round(item["score"], 4),
            "sharpe": round(item["sharpe"], 3),
            "trades": item["trades"],
            "params": item["params"],
        }

    # -- code synthesis ------------------------------------------------------
    async def _synthesize_strategy(self, symbol: str) -> Optional[Dict[str, Any]]:
        """Generate, validate and persist a brand new strategy module."""
        tag = new_id()[:6]
        class_name = f"AIGenerated{tag.capitalize()}"
        strategy_name = f"AI_{tag.upper()}"

        code = await self._generate_code(symbol, class_name, strategy_name, tag)
        if not code:
            return None

        valid, problems = self.validator.validate(code)
        if not valid:
            self.logger.warning("Generated strategy rejected", problems=problems[:4], tag=tag)
            return {"accepted": False, "name": strategy_name, "problems": problems[:4]}

        path = GENERATED_DIR / f"gen_{tag}.py"
        path.write_text(code, encoding="utf-8")
        try:
            module_name = f"strategies.ai_generated.gen_{tag}"
            importlib.invalidate_caches()
            importlib.import_module(module_name)
            data_manager = self.require_service("data_manager")
            df = await data_manager.get_ohlcv(symbol, self.timeframe, 1500)
            candidate = create_strategy(strategy_name, symbol, self.timeframe)
            result = self.engine.run(candidate, df)
        except Exception as exc:  # noqa: BLE001 - discard anything that will not run
            path.unlink(missing_ok=True)
            self.logger.warning("Generated strategy failed the smoke test", tag=tag, error=str(exc))
            return {"accepted": False, "name": strategy_name, "problems": [str(exc)]}

        self.generated_files.append(str(path))
        self.logger.info(
            "New strategy synthesised",
            name=strategy_name,
            path=str(path),
            sharpe=round(result.metrics.sharpe, 3),
            trades=result.metrics.trades,
        )
        return {
            "accepted": True,
            "name": strategy_name,
            "path": str(path),
            "sharpe": round(result.metrics.sharpe, 3),
            "trades": result.metrics.trades,
        }

    async def _generate_code(self, symbol: str, class_name: str, strategy_name: str, tag: str) -> str:
        """Produce strategy source, preferring the LLM when one is configured."""
        if self.llm is not None and self.llm.provider != "heuristic":
            idea = str(self._rng.choice(STRATEGY_IDEAS))
            prompt = LLM_USER_PROMPT.format(
                symbol=symbol,
                timeframe=self.timeframe,
                indicators="rsi, macd, bollinger_bands, atr, adx, stochastic, cci, ema, sma, donchian_channel",
                idea=idea,
                class_name=class_name,
                strategy_name=strategy_name,
            )
            response = await self.llm.complete(prompt, LLM_SYSTEM_PROMPT)
            if response.ok:
                code = self._strip_fences(response.text)
                if "class" in code:
                    return code
            self.logger.warning("LLM generation unusable, falling back to templates", error=response.error)
        return self._synthesize_from_template(class_name, strategy_name, tag)

    @staticmethod
    def _strip_fences(text: str) -> str:
        """Remove markdown code fences from an LLM answer."""
        match = re.search(r"```(?:python)?\n(.*?)```", text, re.DOTALL)
        return match.group(1) if match else text.strip()

    def _synthesize_from_template(self, class_name: str, strategy_name: str, tag: str) -> str:
        """Instantiate a local code template with randomised parameters."""
        template_key = str(self._rng.choice(list(CODE_TEMPLATES)))
        template = CODE_TEMPLATES[template_key]
        common = {
            "class_name": class_name,
            "strategy_name": strategy_name,
            "tag": tag,
            "sl_atr": round(float(self._rng.uniform(1.5, 3.5)), 2),
            "tp_atr": round(float(self._rng.uniform(2.0, 5.0)), 2),
        }
        if template_key == "oscillator_reversion":
            indicator = str(self._rng.choice(["rsi", "cci"]))
            if indicator == "rsi":
                extras = {
                    "indicator": "RSI",
                    "indicator_import": "rsi",
                    "indicator_call": 'rsi(df["close"], int(self.params["period"]))',
                    "period": int(self._rng.integers(7, 25)),
                    "lower": int(self._rng.integers(15, 35)),
                    "upper": int(self._rng.integers(65, 85)),
                }
            else:
                extras = {
                    "indicator": "CCI",
                    "indicator_import": "cci",
                    "indicator_call": 'cci(df["high"], df["low"], df["close"], int(self.params["period"]))',
                    "period": int(self._rng.integers(10, 40)),
                    "lower": int(self._rng.integers(-200, -80)),
                    "upper": int(self._rng.integers(80, 200)),
                }
            return template.format(**common, **extras)
        if template_key == "dual_average":
            fast = int(self._rng.integers(5, 40))
            return template.format(
                **common,
                average=str(self._rng.choice(["sma", "ema"])),
                fast=fast,
                slow=int(fast + self._rng.integers(10, 120)),
                threshold_atr=round(float(self._rng.uniform(0.0, 0.8)), 2),
            )
        entry_period = int(self._rng.integers(15, 80))
        return template.format(
            **common,
            entry_period=entry_period,
            exit_period=int(max(3, entry_period // int(self._rng.integers(2, 5)))),
        )

    # -- reporting -----------------------------------------------------------
    def report(self) -> Dict[str, Any]:
        """Return the current research state for the API and dashboard."""
        return {
            "generation": self.generation,
            "population": [self._describe(item) for item in self.population],
            "hall_of_fame": [self._describe(item) for item in self.hall_of_fame[:10]],
            "generated_files": self.generated_files[-20:],
            "mutation_rate": self.mutation_rate,
            "max_candidates": self.max_candidates,
            "llm_provider": self.llm.provider if self.llm else "none",
        }
