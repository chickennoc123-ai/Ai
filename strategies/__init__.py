"""Strategy library.

Importing this package triggers registration of every bundled strategy through
:func:`core.strategy_registry.register_strategy`.
"""

from strategies.base_strategy import BaseStrategy

__all__ = ["BaseStrategy"]
