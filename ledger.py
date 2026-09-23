import json
import sqlite3


class Ledger:
    def __init__(self, path):
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.execute('CREATE TABLE IF NOT EXISTS portfolio (id INTEGER PRIMARY KEY, data TEXT NOT NULL)')
        self.db.execute('CREATE TABLE IF NOT EXISTS events (txid TEXT PRIMARY KEY, data TEXT NOT NULL)')
        row = self.db.execute('SELECT data FROM portfolio WHERE id=1').fetchone()
        self.state = json.loads(row[0]) if row else {}

    def save(self, event=None):
        # A fill and its resulting account state are committed together, including clearing pending.
        with self.db:
            self.db.execute('INSERT OR REPLACE INTO portfolio VALUES(1,?)', (json.dumps(self.state),))
            if event:
                self.db.execute('INSERT INTO events VALUES(?,?)', (event['txid'], json.dumps(event)))

    def events(self):
        return [json.loads(r[0]) for r in self.db.execute('SELECT data FROM events ORDER BY rowid DESC LIMIT 100')]

    def daily_trades(self, day):
        return sum(e['kind'] in ('BUY', 'SELL') and int(e['time'])//86400 == day for e in self.events())

    def daily_arbs(self, day):
        return sum(e['kind'] == 'ARB' and int(e['time'])//86400 == day for e in self.events())


def apply_event(state, event):
    for asset, delta in event['deltas'].items():
        state['balances'][asset] += delta
        if state['balances'][asset] < 0:
            raise RuntimeError('Negative ledger balance; trading stopped')
    base_delta = event['deltas'].get('BTCB', 0) / 1e18
    quote_delta = event['deltas'].get('USDT', 0) / 1e18
    if event['kind'] == 'BUY':
        state['cost'] += -quote_delta + event['gas_usd']
        state['entry'] = state['cost'] / (state['balances']['BTCB'] / 1e18)
    elif event['kind'] == 'SELL':
        original_qty = state['balances']['BTCB']/1e18 - base_delta
        allocated_cost = state['cost'] * min(1, -base_delta/original_qty) if original_qty else 0
        state['realized'] += quote_delta - event['gas_usd'] - allocated_cost
        state['cost'] -= allocated_cost
        if not state['balances']['BTCB']:
            state['entry'] = state['cost'] = 0
    elif event['kind'] == 'ARB':
        asset = event['arb_asset']
        gained = event['deltas'][asset] / 1e18
        if gained <= 0:
            raise RuntimeError('Arbitrage did not increase the starting token')
        gain_usd = gained * event['asset_price']
        state['arb_gain_at_fill_usd'] = state.get('arb_gain_at_fill_usd', 0.) + gain_usd - event['gas_usd']
        # A BTCB gain remains exposed to BTCB price risk until the position is sold.
        state['realized'] += (gain_usd if asset == 'USDT' else 0.) - event['gas_usd']
        state['last_arb'] = event['time']
        if asset == 'BTCB' and state['balances']['BTCB']:
            state['entry'] = state['cost'] / (state['balances']['BTCB'] / 1e18)
    else:
        state['realized'] -= event['gas_usd']
        if event['kind'] == 'FUND':
            state['realized'] += quote_delta - event.get('funding_usd', 0)
    if event['kind'] in ('BUY', 'SELL'):
        state['last_trade'] = event['time']
    if event['kind'] == 'FUND':
        state['funded'] = True
    state['pending'] = None
