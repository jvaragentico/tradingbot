# Orbit trading bot — review v1.1

An automated BTCB/USDT spot trading bot on BNB Smart Chain, using PancakeSwap V2. BNB is the initial capital and gas asset. After a one-time funding conversion, the strategy buys and sells BTCB. No Binance account is needed. BTCB is a token representing Bitcoin exposure on BNB Chain; it is not native Bitcoin.

**Status:** paper and live processes are running locally. The user's live wallet `0x3062dffa74ec3b8c232a2ae2799e1565702687df` has confirmed BNB funding, token approval and one BTCB buy. The user entered the signing key locally; it was never supplied to this project or GitHub. This update adds a continuously running arbitrage scanner and atomic triangle execution. The existing live process must be restarted locally to load the update. No live arbitrage cycle has been executed or validated yet. The baseline trend backtest lost money. This is an experimental review prototype, not an audited production system.

## Start

Requires Python 3.11 or newer.

```powershell
python -m pip install -r requirements.txt
python app.py
```

Open http://127.0.0.1:8765. The bot and dashboard run while this process and computer remain on and awake. Market observations refresh about every 10 seconds plus API latency; arbitrage quotes refresh about every 30 seconds; the dashboard polls every 3 seconds. The worker is local, not a hosted 24/7 service.

This delivered workspace also contains an ignored `.packages` dependency directory, so `python app.py` works here without modifying the global Python installation.

## Activate actual trading

For this Windows computer and the checked public wallet, follow [RUN_LIVE.md](RUN_LIVE.md) step by step.

1. Review `TEST_REPORT.md` and run `python -m unittest -v test_bot` after installing dependencies.
2. Use a **dedicated BNB Smart Chain wallet** containing $5–$25 total BNB/USDT at startup and no BTCB. Keep other wallets separate. The bot refuses a starting balance above $25 and caps the initial BNB funding swap at $22, retaining native BNB for gas. Market price changes can put a wallet over this limit. Some native BNB is required for gas even when capital is USDT.
3. If the older live bot is already running, stop it with Ctrl+C in its PowerShell window before starting this version. Keep `orbit-live.sqlite3` so the new process resumes its wallet and trade history. Port 8766 keeps the review dashboard on 8765 available:

```powershell
python app.py --mode live --accept-loss-risk --expected-wallet 0x3062dffa74ec3b8c232a2ae2799e1565702687df --port 8766 --key-from-clipboard
```

4. When prompted, copy the dedicated wallet's private key in the wallet app, return to PowerShell and press Enter without pasting. The process reads and clears the clipboard, then checks that the key matches the expected public address before starting its worker. Do not enter a seed phrase. Never paste the key into chat, the dashboard, a GitHub file, or a command argument. Alternatively an operator can provide `BOT_PRIVATE_KEY` through a secure process environment.

On Windows, Python's hidden prompt may not accept paste. The live command above uses `--key-from-clipboard` to avoid that issue. Clipboard contents can be exposed to other local apps or clipboard-history tools while copied.

Starting with these flags authorizes the worker to act automatically. An existing funded live ledger resumes without repeating its funding swap. The bot can act on a trend signal or a qualifying arbitrage quote. Open http://127.0.0.1:8766 and verify the dashboard says **LIVE MODE**. Confirmed actions link to their BscScan transaction hashes. The key is used only in process memory for local signing and is not transmitted to the RPC or dashboard. A compromised host can still steal a key in memory.

The live and paper ledgers are separate (`orbit-live.sqlite3` and `orbit-paper.sqlite3`). Keep the live database: removing it loses the order journal and accounting history. Use `--data-dir PATH` for persistent storage. Run only one bot instance per wallet and data directory. Do not manually move funds or trade from the bot wallet during operation; a balance mismatch pauses trading and invalidates P/L until reviewed.

## Strategy and limits

- Market: BTCB/USDT, allowlisted PancakeSwap V2 pool discovered from the verified factory. Initial BNB/USDT funding is a separate activity.
- Entries/exits: 20-hour and 50-hour simple moving averages with a 0.15% band, using **closed** Kraken BTC/USD candles as a reference. Onchain price must be within 3% of that reference for entries.
- Arbitrage: every 30 seconds, quote four allowlisted, three-pool PancakeSwap V2 triangles across USDT, BTCB and wrapped BNB. A route starts and ends in the same owned token and executes as **one atomic router swap**. It can run at any hour while the process is awake; no route is traded merely to increase the transaction count.
- Arbitrage threshold: at most $20 owned-token notional and at least $5. The onchain quote must show at least $0.10 gross gain: up to $0.03 each for an approval and swap, $0.02 minimum net target and $0.02 quote buffer. The swap's minimum output locks in the original token plus $0.08 at the observed asset price. Arbitrage approvals and swaps each have a $0.03 estimated gas cap, a two-minute cooldown and a limit of 24 successful cycles per UTC day. An approval may still cost gas if the opportunity disappears; a reverted swap still costs gas.
- Position: long only, no leverage, one position, maximum $20 per buy. Sells can close an appreciated position above $20.
- Normal orders: six-hour cooldown and two buy/sell trades per UTC day. A 2% stop trigger, 4% take-profit trigger, and 5% account loss trigger can cause exits outside those limits. The 5% account trigger disables future entries and attempts to close BTCB.
- Gas: native BNB reserve retained. Transactions refused above 1 gwei or $0.15 maximum estimated gas cost each. Insufficient gas can prevent an exit.
- Execution: exact token allowances, 0.5% live slippage ceiling, 120-second transaction deadline, three confirmations before recording fills. Pool fees are included in actual output amounts.
- Reliability: signed transaction hash and intent are saved **before** broadcast. Unknown or timed-out outcomes are reconciled by that hash, never blindly resubmitted. Reverted transactions charge gas and pause trading.
- Manual pause stops new orders including protective exits. It cannot cancel an already-broadcast transaction and does not sell a held position.

Limits reduce some risks; they cannot make losses impossible. Price gaps, network failures, gas shortages, MEV, token/bridge risks, smart-contract failures, and stablecoin depegging remain. A $22-to-$100 target is not a supported forecast. Public APIs require no paid key; gas and trading fees are not free.

## Testing and limitations

```powershell
python -m unittest -v test_bot
```

Tests cover a complete paper funding/buy/sell cycle, atomic arbitrage route selection and net-profit floor, cost accounting, trend signals, next-candle backtesting, loss guards, locally signed transaction encoding, receipt parsing, confirmation depth, transaction reverts, caps, and duplicate prevention after a broadcast timeout. The user's initial funding, approval and BTCB buy have been confirmed onchain. Arbitrage execution remains unit/component tested and has not yet had a funded mainnet acceptance test.

The displayed backtest covers the trend strategy only. It uses about 30 days of Kraken BTC/USD data, next-hour opening fills, 0.25% pool fee plus 0.15% adverse slippage per trade, and two estimated gas charges per trade. It starts with $22 cash and excludes the initial BNB conversion cost. It is not an onchain historical replay: historical liquidity, gas, approvals, MEV and BTCB/USDT basis are not reconstructed. Backtest stops are checked hourly; live stops are polled. The new arbitrage scanner uses forward live quotes and has no historical profit record. USD estimates assume USDT is worth $1.

The service binds only to localhost and verifies the Host header, Origin and a per-process control token for pause/resume. It has no public authentication or TLS layer and must not be exposed directly to the internet. To operate on a remote machine, retain local binding and access through an authenticated SSH tunnel. The SQLite volume and process must persist; a serverless request handler is not suitable for this worker.

Unresolved broadcasts are deliberately left pending for manual inspection. There is no automatic nonce replacement, dropped-transaction recovery, reorg recovery beyond confirmation depth, or external-funds reconciliation in v1.

## Sources

- [BNB Chain public RPC documentation](https://docs.bnbchain.org/bnb-smart-chain/developers/json_rpc/json-rpc-endpoint/)
- [PancakeSwap contract repository](https://github.com/pancakeswap/pancake-smart-contracts)
- [PancakeSwap V2 router source](https://github.com/pancakeswap/pancake-swap-periphery/blob/master/contracts/PancakeRouter.sol)
- [PancakeSwap token list](https://github.com/pancakeswap/token-list)
- [PancakeSwap V2 fee explanation](https://docs.pancakeswap.finance/earn/pancakeswap-pools)
- [Kraken OHLC API](https://docs.kraken.com/api-reference/market-data/get-ohlc-data)
- [Web3.py transaction API](https://web3py.readthedocs.io/en/v7.5.0/web3.eth.html)
