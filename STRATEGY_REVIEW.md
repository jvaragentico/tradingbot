# Strategy review — 23 September 2026

## Decision

The revised trend rules reduce losses in this sample but still lose money. Default new entries therefore use qualifying atomic arbitrage only. Existing BTCB retains its exits. The revised trend is available explicitly as an experiment; neither strategy has demonstrated reliable profitability.

## Historical comparison

720 completed Kraken BTC/USD hourly candles, 50-hour warm-up, evaluated 26 August 2026 13:00 UTC through 23 September 2026 11:00 UTC. One fixed revision was compared with the saved v1.1 baseline; parameters were not retuned after seeing these results.

| Period | Rules | End value from $22 | Trend fills | Maximum drawdown |
|---|---|---:|---:|---:|
| Full sample | v1.1 | $20.7447 | 6 | 6.70% |
| Full sample | revised trend | $20.8264 | 4 | 5.33% |
| First chronological half | v1.1 | $20.7447 | 6 | 6.70% |
| First chronological half | revised trend | $20.8264 | 4 | 5.33% |
| Second chronological half | v1.1 | $20.8211 | 6 | 5.36% |
| Second chronological half | revised trend | $21.6477 | 7 | 4.76% |

Each half starts afresh with $22; the second half uses the preceding 50 bars as warm-up. These splits are diagnostic, not a separately reserved validation dataset. The full sample halted after losses early in the period. The revised second half had one winning closed position out of three; an open position is marked at the final close.

Assumptions: signals use only completed candles, trades fill at the next open, 0.25% fee and 0.15% adverse slippage each way, $0.007 per gas charge and two charges per trend fill. Stops are checked hourly. Initial BNB conversion, historical liquidity, variable gas, MEV, and BTCB/USDT basis are not replayed. USDT is assumed to equal $1. The $17 floor is below the existing $20.90 account guard for this $22 test. This is not a backtest of arbitrage.

## Forward quote check

A read-only BNB Chain check used the current wallet balances, without loading any key or sending any transaction. Six route/size combinations were quoted successfully at block 123559583. The best observed route remained negative. Its gross required edge was about $0.0623 instead of the previous fixed $0.10, while keeping the $0.02 net target and $0.02 quote buffer. It correctly produced no candidate. This verifies data integration and rejection of losing quotes; it provides no evidence of future profitable fills.

## Verification

40 tests passed locally. Coverage includes entry confirmation and spike filtering; no future-candle access; trailing-cost checks; trend reversals and stops bypassing limits; protective exits during a candle API outage; $17 liquidation and permanent halt; stricter 5% guard retention; sub-$5 loss exits; reopening a persisted halt; variable arbitrage sizes; gas budgets; stale-quote rejection before approval; accumulated approval costs; receipt accounting; transaction caps; signing; confirmations; and duplicate prevention.

The v1.2 paper server and dashboard were checked with live market data on port 8767. The dashboard shows runtime version, $17 floor, effective account stop, arbitrage trade size, net gain after gas budgets, and quote errors. No live transaction was sent for acceptance testing. Restart the existing live process locally to activate v1.2; preserve its database.

Sources: [PancakeSwap router](https://developer.pancakeswap.finance/contracts/v2/router-v2), [Kraken OHLC](https://docs.kraken.com/api-reference/market-data/get-ohlc-data).
