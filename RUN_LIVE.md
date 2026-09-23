# Run Orbit on this Windows computer

The public wallet `0x3062dffa74ec3b8c232a2ae2799e1565702687df` initially held about $22.80 in BNB. Its live bot has since confirmed a funding swap, approval and BTCB buy. The bot caps each BTCB buy at $20 and retains BNB for gas. This update adds continuous arbitrage quote scanning, but profitable routes may be rare. The trend strategy's recent backtest lost money; live losses remain possible.

1. Open **PowerShell** on the same Windows computer. Do not put a private key into chat, a browser, GitHub, or a command argument.
2. Go to the delivered project:

   ```powershell
   Set-Location 'C:\Users\jojd1\Documents\Codex\2026-09-23\github-plugin-github-openai-curated-remote-3\outputs\trading-bot-v1'
   ```

3. Verify Python and the tests:

   ```powershell
   python --version
   $env:PYTHONPATH = (Resolve-Path .packages).Path
   python -m unittest -q test_bot
   ```

   This delivered copy includes `.packages`, so the tests and app run here without installing anything. The `PYTHONPATH` line makes those bundled dependencies available to the test command. For a fresh GitHub clone, first run `python -m pip install -r requirements.txt`.

4. **Stop the older live bot with Ctrl+C in its PowerShell window.** Wait until its process exits; do not start two processes for the same wallet and ledger. Keep `orbit-live.sqlite3`, which contains its confirmed transaction history. Then start the updated live worker:

   ```powershell
   python app.py --mode live --accept-loss-risk --expected-wallet 0x3062dffa74ec3b8c232a2ae2799e1565702687df --port 8766 --key-from-clipboard
   ```

5. The bot displays `Copy the account private key in your wallet app, then return here and press Enter`. **After that prompt appears**, copy the account private key in your wallet app, return to PowerShell, and press Enter. **Do not paste into PowerShell.** The bot reads the clipboard once and clears it. Use only a dedicated bot wallet. The bot checks that the key derives the `--expected-wallet` address before any trading worker starts. If this is a different wallet from the address above, replace `--expected-wallet` with the new wallet's public 0x address before running the command. If you do not have the account private key, stop here; a public address or seed phrase cannot be entered into this mode.
6. Open **http://127.0.0.1:8766** and verify the header says **LIVE MODE**, the wallet address matches, the health indicator is green, and the **24-hour arbitrage watch** shows a fresh quote. Keep the PowerShell window and computer powered on and awake. The existing funded ledger resumes; it does not repeat the BNB funding swap. The trend strategy can enter and exit BTCB, and the arbitrage scanner checks four atomic triangle routes every 30 seconds. It trades only when a route's quoted gain exceeds its gas budget, minimum gain and buffer. Check the Trades table and BscScan links for confirmed transactions.
7. Use **Pause** on the live dashboard to stop new orders. Pause does not cancel an already-broadcast transaction or sell a held BTCB position. Use Ctrl+C in the live PowerShell window to stop the worker entirely. Keep `orbit-live.sqlite3`; it records transactions and prevents duplicate submissions after an uncertain broadcast.

The review dashboard stays at **http://127.0.0.1:8765** in paper mode. The live process uses port 8766, and the two modes use separate ledgers. Never treat a paper trade as a real fill.

There is no way to make losses impossible. Refusing to sell below entry price would merely keep a depreciating token in the wallet and disable the protective exit. The existing 2% stop trigger, 5% account loss guard, $20 buy cap, slippage and gas ceilings limit selected risks but cannot promise a maximum realized or unrealized loss.
