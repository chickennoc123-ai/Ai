# EA Generator — machinery demonstration

**These files are NOT a trading strategy. Do not run them on any account.**

The AGLE Strategy Factory found **no edge** in Cycle 3 (0 of 43 hypotheses
cleared the pre-registered internal-validation gates), so there is no
qualified candidate to package. The real sealed holdout was never opened.

What is in this directory is the *generator's output shape*, produced from a
**synthetic candidate** (`DEMO-SYNTHETIC-NOT-TRADABLE`) whose GEN 14 "PASS"
was written into a throwaway registry purely to exercise the code path. Its
parameters were never validated against market data.

It exists to answer one question: *if a real edge is ever qualified, what does
the factory emit?* Answer — MT5 (`.mq5`), MT4 (`.mq4`), TradingView (`.pine`),
and a `manifest.json` carrying the frozen spec hash.

A genuinely tradable package would be written to `artifacts/ea/` by
`factory_pipeline.py`, and only after a candidate passed GEN 14 against the
real sealed holdout. That directory is empty, which is the correct and
honest state of this project today.
