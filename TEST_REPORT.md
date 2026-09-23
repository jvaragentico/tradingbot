# V1.1 verification — 23 September 2026

- 26 unit/component tests pass locally on Python 3.13.7 with Web3.py 7.16.0. They cover the original execution controls plus atomic triangle selection, net-profit threshold, adverse quote refusal, one-transaction route construction, paper fills, and receipt accounting.
- GitHub Actions runs the same tests on Linux/Python 3.12 for every published update.
- Confirmed BNB Smart Chain chain ID 56; verified PancakeSwap router factory and WBNB identities, token decimals, and both pool token sets directly through RPC.
- Resolved BTCB/USDT V2 pool: `0x3F803EC2b816Ea7F06EC76aA2B6f2532F9892d62`.
- The current live wallet confirmed a BNB-to-USDT funding swap, an exact USDT approval, and a BTCB buy. Public BNB Chain receipts for all three transactions show success; the live dashboard lists their hashes.
- The arbitrage scanner read four real PancakeSwap V2 router quotes for the funded wallet. The best BTCB triangle at block 123556031 was about **-$0.1133 before gas** on about $19.92 notional, below the required **+$0.10** quote threshold. No arbitrage order was justified or sent.
- Retrieved 720 completed hourly candles from Kraken; excluded its unfinished candle.
- Historical baseline snapshot: ending equity **$20.7441**, versus **$24.0639** for the hold-BTC reference, with **6 trades**. Results will change as the rolling window updates. This test does not establish profitability.
- The running paper worker completed initial funding and a BTCB buy; after upgrade its arbitrage scanner reports fresh quotes with zero router errors.
- Dashboard renders balances, market freshness, signal, funding, buys/sells, transaction state and historical results. Local HTTP controls use a per-process token and Host/Origin checks.
- Browser-tested pause and resume controls in paper mode.

The wallet's signing key was entered by the user locally and was never shared with this task or repository. **The new arbitrage branch has not sent a real-money cycle.** An arbitrage approval may spend gas even if the opportunity disappears, and a reverted cycle can spend gas. Public quotes and mocked receipts do not prove future profitability. The existing live process must be restarted by the user to load v1.1; this task cannot recover its key or restart it unattended.
