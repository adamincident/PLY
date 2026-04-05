# Risk Engine Overview

Risk validation must run before any order decision (paper or live).

## Mandatory controls

- Max position size (absolute and % of equity)
- Max daily loss
- Market and outcome exposure caps
- Cooldown windows after loss streaks
- Circuit breaker when health checks fail or volatility spikes

## Validation order (suggested)

1. Portfolio-level kill switches.
2. Signal freshness and duplication guard.
3. Liquidity/spread/slippage constraints.
4. Exposure checks.
5. Final approval gate.

## Important

The architecture is designed for speed, but risk checks are never optional.
