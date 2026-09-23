# Start the updated live bot

The bot runs independently of Codex usage. Keep Windows awake and online and leave its PowerShell window open. Version 1.3 adds five-pair scanning, V3 fee-tier arbitrage, faster batched reads, and the $27 target display; the $17 floor and stricter 5% guard remain. Saving the files does not update an already-running Python process.

1. On the current live dashboard, wait until **No transaction awaiting confirmation** is shown. In the PowerShell window running the live bot, press **Ctrl+C** and wait for the command prompt.
2. Keep `orbit-live.sqlite3`. In that same PowerShell window, run:

   ```powershell
   Set-Location 'C:\Users\jojd1\Documents\Codex\2026-09-23\github-plugin-github-openai-curated-remote-3\outputs\trading-bot-v1'
   python app.py --mode live --accept-loss-risk --expected-wallet 0x3062dffa74ec3b8c232a2ae2799e1565702687df --port 8766 --key-from-clipboard --equity-floor 17
   ```

3. When the key prompt appears, copy the **dedicated wallet account's private key** in your wallet application. Return to PowerShell and press **Enter without pasting**. The program reads and clears the clipboard and verifies the public address. Do not send a seed phrase or private key in chat.
4. Open http://127.0.0.1:8766. Confirm **V1.3**, **LIVE MODE**, **MARKET CONNECTED**, your wallet, and **Portfolio stop floor $17.00**. The active account stop also includes the existing 5% guard, so it can be higher than $17 (about $21.69 for the recorded initial $22.83).
5. Leave the process open. It manages existing BTCB and scans arbitrage. New trend buys are disabled by default because testing still showed losses. A profitable quote is required for a new arbitrage cycle.

At the active account threshold, the bot attempts to sell BTCB into USDT and latches a stop that prevents further trading, including after a restart. This is a portfolio-value trigger, not a guaranteed minimum wallet value. Fees, price movements, missing gas, outages, a paused worker, or an unresolved transaction can delay or prevent the exit.

The existing 2% position stop and 4% take-profit remain. All exits bypass entry cooldowns and limits. Pause stops new orders including exits and does not liquidate a position. Run only one live process for this wallet. Do not delete the ledger or manually trade from the wallet while the bot runs.

## Verify locally

```powershell
$env:PYTHONPATH = (Resolve-Path .packages).Path
python -m unittest discover -q
```

For a fresh GitHub clone, install `requirements.txt` first instead of using `.packages`. 55 automated tests cover stops, persisted halt state, accounting, and transaction checks. The paper preview on port 8768 is a simulation and does not execute real wallet transactions.

The expanded scanner uses PancakeSwap V3 as well as V2. Any allowance is for the exact amount on the specific router. The bot never grants an unlimited allowance. Actual transaction estimates still must fit the gas budget before a broadcast. $27 in five hours is not a guaranteed outcome; the current forward checks found no qualifying opportunity.
