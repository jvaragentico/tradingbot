"""One transparent strategy, shared by paper mode, live mode, and backtests."""
FAST, SLOW = 20, 50
BAND = 0.0015
COOLDOWN = 6 * 3600
MAX_DAILY = 2
STOP = 0.02
TAKE_PROFIT = 0.04


def signal(closes):
    if len(closes) < SLOW:
        return 'WAIT', 0, 0
    fast, slow = sum(closes[-FAST:]) / FAST, sum(closes[-SLOW:]) / SLOW
    target = 'BUY' if fast > slow * (1+BAND) else 'SELL' if fast < slow * (1-BAND) else 'HOLD'
    return target, fast, slow


def action(closes, holding, price, entry_price, last_trade, now, trades_today):
    target, _, _ = signal(closes)
    # Risk exits bypass entry cooldown and daily entry limit. Slippage/gaps can exceed the stop.
    if holding and entry_price:
        if price <= entry_price * (1-STOP):
            return 'SELL', '2% stop trigger'
        if price >= entry_price * (1+TAKE_PROFIT):
            return 'SELL', '4% take-profit trigger'
    if now - last_trade < COOLDOWN or trades_today >= MAX_DAILY:
        return 'HOLD', 'Cooldown or daily trade limit'
    if not holding and target == 'BUY':
        return 'BUY', '20/50-hour trend turned positive'
    if holding and target == 'SELL':
        return 'SELL', '20/50-hour trend turned negative'
    return 'HOLD', 'Waiting for a qualifying entry or exit'


def backtest(rows, gas_usd):
    cash, qty, cost, entry, last_trade = 22.0, 0.0, 0.0, 0.0, -1e20
    daily, trades, curve = {}, [], []
    halted, peak, max_dd = False, 22.0, 0.0
    for i in range(SLOW, len(rows)):
        row, prior = rows[i], rows[i-1]
        t, p = row['time'], row['open']
        day = t // 86400
        before = cash + qty * prior['close']
        if before <= 22 * .95:
            halted = True
        side, reason = action([r['close'] for r in rows[:i]], qty > 0, prior['close'], entry, last_trade, t, daily.get(day, 0))
        if halted:
            side = 'SELL' if qty else 'HOLD'
            reason = '5% account loss guard'
        if side == 'BUY' and cash >= 5 + gas_usd * 2:
            spend = min(20, cash - gas_usd * 2)
            qty = spend * .9975 * .9985 / p
            cost = spend + gas_usd * 2
            cash -= cost
            entry = cost / qty
        elif side == 'SELL' and qty:
            cash += qty * p * .9975 * .9985 - gas_usd * 2
            qty, cost, entry = 0.0, 0.0, 0.0
        else:
            side = 'HOLD'
        if side != 'HOLD':
            trades.append({'time': t, 'side': side, 'price': p, 'reason': reason})
            last_trade = t
            daily[day] = daily.get(day, 0) + 1
        value = cash + qty * row['close']
        peak = max(peak, value)
        max_dd = max(max_dd, 1-value/peak)
        curve.append({'time': t, 'value': value})
    return {'start': rows[SLOW]['time'], 'end': rows[-1]['time']+3600,
            'end_usd': round(cash + qty*rows[-1]['close'], 4),
            'hold_end_usd': round(22 * rows[-1]['close']/rows[SLOW]['open'], 4),
            'trade_count': len(trades), 'max_drawdown_pct': round(max_dd*100, 2),
            'halted': halted, 'trades': trades, 'curve': curve,
            'assumptions': 'Kraken BTC/USD proxy; signals use completed hours, fills use next open. 0.25% fee + 0.15% adverse slippage each way and two estimated gas charges per trade. Stops checked hourly. Excludes initial BNB funding cost; no historical pool-depth or gas replay. USDT assumed $1. Not proof of future profit.'}
