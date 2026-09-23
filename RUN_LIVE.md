# Run Orbit on this Windows computer

The public wallet `0x9D7CC5DAC432Ac61303552Cd8835fF34Aa2C39Ab` held 0.029066815 BNB (about $22.78) when checked on September 23, 2026. Recheck the wallet before starting because prices and balances change. The bot caps its first BNB-to-USDT funding swap at $22 and keeps BNB for gas; each BTCB buy is capped at $20. It trades BTCB/USDT automatically when its rules produce a signal. The strategy's recent backtest lost money; live losses remain possible.

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

4. Start the live worker in that PowerShell window:

   ```powershell
   python app.py --mode live --accept-loss-risk --expected-wallet 0x9D7CC5DAC432Ac61303552Cd8835fF34Aa2C39Ab --port 8766
   ```

5. At `Dedicated bot wallet private key (hidden):`, type or paste **only in that local terminal** the private key controlling the public address above, then press Enter. The characters will not appear on screen. Use only a dedicated bot wallet. The bot checks that the key derives that exact address before any trading worker starts. If you do not have that key, stop here; a public address cannot authorize a trade.
6. Open **http://127.0.0.1:8766** and verify the header says **LIVE MODE**, the wallet address matches, and the health indicator is green. Keep the PowerShell window and computer running. The worker may exchange BNB for USDT immediately, then enter and exit BTCB based on closed hourly signals. It can also remain idle if no signal qualifies. Check the Trades table and BscScan links for confirmed transactions.
7. Use **Pause** on the live dashboard to stop new orders. Pause does not cancel an already-broadcast transaction or sell a held BTCB position. Use Ctrl+C in the live PowerShell window to stop the worker entirely. Keep `orbit-live.sqlite3`; it records transactions and prevents duplicate submissions after an uncertain broadcast.

The review dashboard stays at **http://127.0.0.1:8765** in paper mode. The live process uses port 8766, and the two modes use separate ledgers. Never treat a paper trade as a real fill.

There is no way to make losses impossible. Refusing to sell below entry price would merely keep a depreciating token in the wallet and disable the protective exit. The existing 2% stop trigger, 5% account loss guard, $20 buy cap, slippage and gas ceilings limit selected risks but cannot promise a maximum realized or unrealized loss.

