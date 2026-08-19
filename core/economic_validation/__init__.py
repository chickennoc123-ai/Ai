"""ML-001 Generation 4 — Candidate Economic Validation.

This package contains the evidence-producing machinery for Generation 4:
candidate freeze, data eligibility, temporal/target leakage auditing,
partition sealing, deterministic rule execution, metric computation,
walk-forward, robustness, cost stress, statistics, multiple-testing
correction, and the Economic Validation Gate.

Design rule that governs every module here: **evidence is produced by
exactly one module and consumed by another.** ``evg.py`` in particular
never computes an economic number — it only reads records other modules
wrote. See ``ML-001-GENERATION-4-SPEC.md``.
"""
