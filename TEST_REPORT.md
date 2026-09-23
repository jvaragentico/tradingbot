# V1 verification — 23 September 2026

- 20 unit/component tests cover the execution path on Python 3.13.7 with Web3.py 7.16.0, including refusal to start a duplicate order worker, stale data, external wallet changes, the $22 funding cap, and clipboard key clearing and format checks.
- GitHub Actions passed the latest published 18-test build on Linux/Python 3.12. The workflow reruns for every published update.
- Confirmed BNB Smart Chain chain ID 56; verified PancakeSwap router factory and WBNB identities, token decimals, and both pool token sets directly through RPC.
- Resolved BTCB/USDT V2 pool: `0x3F803EC2b816Ea7F06EC76aA2B6f2532F9892d62`.
- Read a live router quote for 20 USDT: approximately 0.00023210 BTCB at the time of the check. This was a read-only quote, not an executed order.
- Retrieved 720 completed hourly candles from Kraken; excluded its unfinished candle.
- Historical baseline snapshot: ending equity **$20.7441**, versus **$24.0639** for the hold-BTC reference, with **6 trades**. Results will change as the rolling window updates. This test does not establish profitability.
- Running paper worker completed the initial funding conversion and a BTCB buy. Account value was approximately $21.81 after modeled costs and market movement at 10:12 UTC.
- Dashboard renders balances, market freshness, signal, funding, buys/sells, transaction state and historical results. Local HTTP controls use a per-process token and Host/Origin checks.
- Browser-tested pause and resume controls in paper mode.

The user's public wallet was checked on BNB Chain and held 0.029066815 BNB, approximately $22.78 at the observed pool price. No private key was supplied. **No real-money transaction was sent.** Mainnet execution, gas estimation from a funded wallet, live token approvals and the full funded settlement cycle still require a small supervised acceptance test. Do not mistake mocked receipt tests or a public quote for that acceptance test.
