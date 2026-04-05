# Paper Trading Guide

The system defaults to paper trading mode (`Portfolio.mode = PAPER`).

## Workflow

1. Ingest normalized market and wallet events.
2. Generate validated copy-trade signals.
3. Simulate execution by writing `PaperTrade` records.
4. Update `Position` and `Portfolio` balances.

## Principles

- No real orders are sent in paper mode.
- Every simulated trade should be persisted for replay and audit.
- PnL is tracked both realized and unrealized.

## TODO (future phases)

- Implement event-driven fill simulator.
- Implement market resolution settlement pipeline.
- Add latency and slippage simulation knobs.
