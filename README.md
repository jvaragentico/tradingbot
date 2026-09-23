# Orbit trading bot — v1.3

Local BNB Chain bot and dashboard using PancakeSwap V2. BNB supplies initial capital and transaction gas. Python runs independently of Codex and does not use an AI API. It runs while the computer is awake, online, and its PowerShell process remains open.

## What changed in v1.3

- Expanded markets: USDT routes through **BNB, BTCB, ETH, USDC, and CAKE**. V2 uses three-pool triangles; V3 compares distinct fee-tier pools for an atomic USDT → asset → USDT cycle. The intermediate asset is not held after a successful cycle.
- V3 fee tiers: 0.01%, 0.05%, and 0.25%. Only pairs with two different eligible pools are compared. The same pool is never reused in a cycle. V3 factory, router, quoter, token addresses, decimals, and available liquidity are checked.
- V2 quotes, V3 pool data, and balances use batched reads pinned to a block. The scanner screens V3 routes by a no-impact price bound, quotes up to eight promising routes (or the best route for diagnostics), then applies exact output and gas thresholds. Each eligible pool must hold at least 50,000 USDT and have active liquidity. Passing this floor alone does not guarantee depth across price ranges; the exact quoter handles price impact.
- Public RPC reads have bounded failover. Broadcasts are never automatically retried. Historical candle refresh runs separately so it cannot block arbitrage or stops.
- The dashboard tracks the requested **$27 target**, completed positions, wins, position P/L including gas/approvals, and route availability. The requested five-hour horizon is an aspiration, not a forecast or a timed trading override.

55 automated tests pass. Three read-only chain checks each returned 27 exact quotes in about 5.1 seconds with zero quote errors. The best observed V3 route had 0.06% combined pool fees but was still negative after gas, so it was correctly rejected. No profitable mainnet V3 fill has been validated. See [V13_REVIEW.md](V13_REVIEW.md).

## Existing controls

- Arbitrage is the default for new trades. Existing BTCB positions retain managed exits. New directional trend positions require `--enable-experimental-trend`; the reference trend backtest still loses money.
- The scanner compares $5, $10, and up to $20 sizes across allowlisted V2 triangles and V3 round trips. Only funded starting assets are quoted. Every cycle begins and ends in the same token in one atomic router swap.
- The profit threshold uses current gas prices with enforced approval and swap budgets, 50% estimation headroom, a $0.02 net target, and a $0.02 quote buffer. Each transaction budget is capped at $0.03. Previously paid arbitrage approval costs are carried into subsequent thresholds until a cycle succeeds.
- Quotes are rechecked before spending approval gas. A smaller trade can qualify when the larger trade has excessive price impact. Pool fees are already included in router output.
- All position exits bypass entry cooldowns and daily limits. A 2% stop and 4% take-profit remain. After a 2% advance, a 1% pullback can trigger a trailing exit if estimated proceeds cover position costs plus 0.2%.
- Protective exits run before the optional historical-data refresh or arbitrage scan. Loss exits can close holdings worth less than $5.
- A **$17 portfolio stop floor** is enabled by default. The existing 5% account guard can stop earlier: the active trigger is `max($17, initial portfolio value × 0.95)`. When triggered, the bot records a durable halt, attempts to sell BTCB into USDT, then pauses trading. Automatic resume is blocked even after a restart.

These are execution rules, not guaranteed returns or guaranteed exit prices. Reverted transactions and abandoned approvals still cost gas. A successful cycle increasing BTCB remains exposed to BTCB price changes. The reference data assumes USDT is worth $1. The account stop can execute below its trigger during gaps, delays, or unavailable gas.

## Run

Requires Python 3.11+:

```powershell
python -m pip install -r requirements.txt
python -m unittest discover -q
python app.py
```

Paper mode is the default at http://127.0.0.1:8765. This delivered Windows copy also has an ignored `.packages` dependency directory. See [RUN_LIVE.md](RUN_LIVE.md) for the local restart and key-entry steps.

```powershell
python app.py --mode live --accept-loss-risk --expected-wallet 0x3062dffa74ec3b8c232a2ae2799e1565702687df --port 8766 --key-from-clipboard --equity-floor 17
```

The private key is read locally and checked against the public address. Never supply it in chat, a command argument, or a repository file. The clipboard mode reads and clears the copied key after Enter; it does not accept a seed phrase. A compromised computer can still expose a key in memory.

Keep `orbit-live.sqlite3` and its transaction journal. Restarting with the same wallet and data directory resumes the existing balance and history. Do not start two bots for the same wallet or move wallet funds outside the bot: a mismatch pauses trading and invalidates P/L. A new ledger requires a dedicated wallet with $5–$25 of BNB/USDT and no BTCB; a starting balance already below the configured equity floor halts immediately.

## Execution and operation

- At most one legacy/experimental long BTCB position, no leverage; maximum $20 per buy and $22 initial BNB funding conversion, retaining BNB for gas.
- Experimental trend: closed 20/50-hour averages, a 0.15% band, confirmation now and two hours earlier, rising fast average, and price between the fast average and 1.5% above it. The onchain entry price must also be within 3% of the closed Kraken BTC/USD reference. Six-hour entry cooldown and two trend fills per UTC day; exits bypass both limits.
- Arbitrage: scans about every 10 seconds plus RPC latency, a bounded quote-scan budget, two-minute cooldown, and 24 successful cycles per UTC day. No qualifying quote means no arbitrage order.
- Chain observations and account stops run about every 10 seconds plus API latency. Dashboard updates every 3 seconds. Stops are software polling rules; they are not orders resting on the blockchain.
- Live slippage limit 0.5%, exact token approvals, 120-second normal swap deadline, 60-second arbitrage deadline. Three confirmations are required before recording actual receipt transfers and gas costs.
- Refuses transactions above 1 gwei, above their gas budget, or with stale market data. Missing BNB or an unavailable RPC can prevent an exit.
- Transaction intent and signed hash are saved before broadcast. Uncertain outcomes are reconciled by hash without automatic resubmission. A revert charges gas and pauses trading.
- **Pause stops all new orders, including exits.** It does not cancel a pending transaction or sell the current holding. The account stop requires the worker to be running and unpaused with a reconciled wallet.

The service binds to localhost and validates Host, Origin, and a per-process control token. It must not be exposed directly to the internet. There is no restart after reboot, automatic nonce replacement, full reorg recovery, or external-funds reconciliation.

## Evidence

See [STRATEGY_REVIEW.md](STRATEGY_REVIEW.md) for the comparison, forward quote check, and limitations. 55 automated tests pass. Synthetic profitable cycles verify accounting and safeguards, not real-world opportunity frequency. No live arbitrage fill has been validated by this revision. Previous funding, approval, and a BTCB buy exist in the live ledger; v1.3 needs a local restart before its new rules apply.

## Sources

- [PancakeSwap V2 router documentation](https://developer.pancakeswap.finance/contracts/v2/router-v2)
- [PancakeSwap router source](https://github.com/pancakeswap/pancake-swap-periphery/blob/master/contracts/PancakeRouter.sol)
- [Kraken OHLC API](https://docs.kraken.com/api-reference/market-data/get-ohlc-data)

- [PancakeSwap V3 addresses](https://developer.pancakeswap.finance/contracts/v3/addresses)
- [PancakeSwap token list](https://github.com/pancakeswap/token-list/blob/main/src/tokens/pancakeswap-extended.json)
- [Multicall3 source](https://github.com/mds1/multicall3/blob/main/src/Multicall3.sol)
- [BNB Chain RPC endpoints](https://docs.bnbchain.org/bnb-smart-chain/developers/json_rpc/json-rpc-endpoint/)
