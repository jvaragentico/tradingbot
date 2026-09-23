"""One transparent strategy, shared by paper mode, live mode, and backtests."""
FAST, SLOW = 20, 50
BAND = 0.0015
COOLDOWN = 6 * 3600
MAX_DAILY = 2
STOP = 0.02
TAKE_PROFIT = 0.04
VERSION = '1.3'
TRAIL_ARM = 0.02
TRAIL_DISTANCE = 0.01
MAX_ENTRY_EXTENSION = 0.015
FILL_FACTOR = .9975 * .9985


def signal(closes):
    if len(closes) < SLOW:
        return 'WAIT', 0, 0
    fast, slow = sum(closes[-FAST:]) / FAST, sum(closes[-SLOW:]) / SLOW
    target = 'BUY' if fast > slow * (1+BAND) else 'SELL' if fast < slow * (1-BAND) else 'HOLD'
    return target, fast, slow


def protective_exit(price, entry_price, peak=0, exit_net=None, cost=0):
    if not entry_price:
        return None
    if price <= entry_price * (1-STOP):
        return '2% stop trigger'
    if price >= entry_price * (1+TAKE_PROFIT):
        return '4% take-profit trigger'
    if (peak >= entry_price * (1+TRAIL_ARM) and price <= peak * (1-TRAIL_DISTANCE)
            and exit_net is not None and exit_net >= cost * 1.002 and cost > 0):
        return '1% trailing exit after 2% advance; estimated proceeds cover costs'
    return None


def action(closes, holding, price, entry_price, last_trade, now, trades_today,
           peak=0, exit_net=None, cost=0):
    target, fast, _ = signal(closes)
    # All exits bypass entry throttles. Slippage/gaps can exceed the stop.
    if holding and entry_price:
        reason = protective_exit(price, entry_price, peak, exit_net, cost)
        if reason:
            return 'SELL', reason
    if holding:
        if target == 'SELL':
            return 'SELL', '20/50-hour trend turned negative'
        return 'HOLD', 'Managing the open position; waiting for an exit'
    if now - last_trade < COOLDOWN or trades_today >= MAX_DAILY:
        return 'HOLD', 'Cooldown or daily trade limit'
    if not holding and target == 'BUY':
        if len(closes) < SLOW+3 or signal(closes[:-2])[0] != 'BUY':
            return 'HOLD', 'Waiting for trend confirmation across three closed hours'
        previous_fast = sum(closes[-FAST-3:-3]) / FAST
        if fast <= previous_fast:
            return 'HOLD', 'Fast trend is losing momentum'
        if not fast <= closes[-1] <= fast * (1+MAX_ENTRY_EXTENSION):
            return 'HOLD', 'Waiting for price above its fast average without chasing a spike'
        if price > fast * (1+MAX_ENTRY_EXTENSION) or price < fast:
            return 'HOLD', 'Onchain price is outside the entry band'
        return 'BUY', 'Confirmed rising 20/50-hour trend within entry band'
    return 'HOLD', 'Waiting for a qualifying entry or exit'


def backtest(rows, gas_usd):
    cash, qty, cost, entry, last_trade = 22.0, 0.0, 0.0, 0.0, -1e20
    daily, trades, curve = {}, [], []
    halted, peak, max_dd, position_peak = False, 22.0, 0.0, 0.0
    closed_pnls = []
    for i in range(SLOW, len(rows)):
        row, prior = rows[i], rows[i-1]
        t, p = row['time'], row['open']
        day = t // 86400
        before = cash + qty * prior['close']
        if before <= 22 * .95:
            halted = True
        if qty:
            position_peak = max(position_peak, prior['close'])
        side, reason = action([r['close'] for r in rows[:i]], qty > 0, prior['close'], entry, last_trade, t, daily.get(day, 0),
                              position_peak, qty * prior['close'] * FILL_FACTOR - gas_usd * 2, cost)
        if halted:
            side = 'SELL' if qty else 'HOLD'
            reason = '5% account loss guard'
        if side == 'BUY' and cash >= 5 + gas_usd * 2:
            spend = min(20, cash - gas_usd * 2)
            qty = spend * FILL_FACTOR / p
            cost = spend + gas_usd * 2
            cash -= cost
            entry = cost / qty
            position_peak = p
        elif side == 'SELL' and qty:
            proceeds = qty * p * FILL_FACTOR - gas_usd * 2
            closed_pnls.append(proceeds - cost)
            cash += proceeds
            qty, cost, entry = 0.0, 0.0, 0.0
            position_peak = 0.0
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
            'closed_trades': len(closed_pnls), 'winning_trades': sum(p > 0 for p in closed_pnls),
            'closed_pnl_usd': round(sum(closed_pnls), 4),
            'liquidation_usd': round(cash + (qty*rows[-1]['close']*FILL_FACTOR-gas_usd*2 if qty else 0), 4),
            'assumptions': 'Kraken BTC/USD proxy; signals use completed hours, fills use next open. 0.25% fee + 0.15% adverse slippage each way and two estimated gas charges per trade. Stops checked hourly. Excludes initial BNB funding cost; no historical pool-depth or gas replay. USDT assumed $1. Not proof of future profit.'}
