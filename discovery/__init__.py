"""
ML-001 Discovery layer (GEN 7-11).

GEN 8: observatory.py  -- market evidence, computed on DEV data only
GEN 7: engine.py       -- evidence -> hypothesis, with refuted-family firewall
GEN 9: features.py     -- train-only feature discovery with complexity penalty
GEN 10: composition.py -- strategy grammar + compositional search
GEN 11: regime.py      -- condition-specific edge analysis

HARD RULE: nothing in this package may read anything under data/holdout/.
Every module enforces the guard at load time (see _guards.py).
"""
