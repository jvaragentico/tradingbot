"""BTCB/USDT trading, using BNB as initial capital and gas."""
import copy
import threading
import time
import uuid
from pathlib import Path
from execution import LiveExecutor
from ledger import Ledger, apply_event
from market import Chain, UNIT, amount_out, candles, equity
from strategy import action, backtest, signal


class TradingBot:
    def __init__(self, mode='paper', private_key=None, data_dir=None):
        if mode not in ('paper', 'live'):
            raise ValueError('Mode must be paper or live')
        self.mode, self.chain = mode, Chain()
        self.ledger = Ledger(Path(data_dir or Path(__file__).parent) / f'orbit-{mode}.sqlite3')
        self.executor = LiveExecutor(self.chain, self.ledger, private_key) if mode == 'live' else None
        self.lock = threading.RLock()
        self.market, self.rows, self.test, self.observed = {}, [], {}, None
        self.error, self.decision, self.last_candles = '', 'Waiting for fresh market data', 0
        self.stop_event = threading.Event()
        self.worker = threading.Thread(target=self.loop, daemon=True)

    def initialize(self):
        s = self.ledger.state
        if s:
            if s['mode'] != self.mode or (self.executor and s['wallet'] != self.executor.address):
                raise RuntimeError('Database belongs to another mode or wallet; use a separate data directory')
            return
        b = self.chain.balances(self.executor.address) if self.executor else {
            'BNB': int(22/self.market['BNB']['price']*UNIT), 'BTCB': 0, 'USDT': 0}
        initial = equity(b, self.market)
        if not 5 <= initial <= 22.000001 or b['BTCB']:
            raise RuntimeError('Use a dedicated wallet holding $5–$22 total BNB/USDT and no BTCB. No transaction sent.')
        self.ledger.state = {'mode': self.mode, 'wallet': self.executor.address if self.executor else None,
            'balances': b, 'initial': initial, 'initial_btc_price': self.market['BTCB']['price'],
            'created': time.time(), 'paused': False, 'pause_reason': '', 'loss_halt': False,
            'pnl_valid': True, 'cost': 0., 'entry': 0., 'realized': 0., 'last_trade': 0.,
            'funded': b['USDT']/UNIT >= 5, 'pending': None}
        self.ledger.save()

    def paper_fill(self, kind, amount, reason):
        s = copy.deepcopy(self.ledger.state)
        source = 'BNB' if kind == 'FUND' else 'USDT' if kind == 'BUY' else 'BTCB'
        pool = self.market['BNB' if kind == 'FUND' else 'BTCB']
        ri, ro = (pool['quote_reserve'], pool['base_reserve']) if kind == 'BUY' else (pool['base_reserve'], pool['quote_reserve'])
        received = amount_out(amount, ri, ro)*9985//10000
        gas = self.market['gas_price']*(180_000 if kind == 'FUND' else 360_000)
        deltas = {'BNB': -gas, 'BTCB': 0, 'USDT': 0}
        deltas[source] -= amount
        deltas['BTCB' if kind == 'BUY' else 'USDT'] += received
        event = {'txid': 'paper-'+uuid.uuid4().hex, 'time': time.time(), 'kind': kind,
            'deltas': deltas, 'gas_usd': gas/UNIT*self.market['BNB']['price'], 'reason': reason,
            'funding_usd': amount/UNIT*self.market['BNB']['price'] if kind == 'FUND' else 0, 'execution': 'PAPER'}
        apply_event(s, event)
        self.ledger.state = s
        self.ledger.save(event)

    def decide(self):
        s, m = self.ledger.state, self.market
        if s['pending'] or s['paused']:
            self.decision = s['pause_reason'] or 'Waiting for transaction confirmations'
            return
        b = s['balances']
        if equity(b, m) <= s['initial']*.95:
            s['loss_halt'] = True
            self.ledger.save()
        if s['loss_halt'] and not b['BTCB']:
            self.set_paused(True, 'Account loss guard triggered. New entries are disabled.')
            return
        if m['gas_price'] > 1_000_000_000:
            self.decision = 'Gas exceeds the 1 gwei limit'
            return
        if not s['funded']:
            amount = b['BNB'] - max(int(.0003*UNIT), m['gas_price']*800_000)
            if amount/UNIT*m['BNB']['price'] < 5:
                self.decision = 'Insufficient BNB after retaining the gas reserve'
                return
            kind, reason = 'FUND', 'Prepare USDT trading capital from the initial BNB'
        else:
            kind, reason = action([r['close'] for r in self.rows], bool(b['BTCB']), m['BTCB']['price'],
                s['entry'], s['last_trade'], time.time(), self.ledger.daily_trades(int(time.time())//86400))
            if s['loss_halt']:
                kind, reason = 'SELL', 'Account loss guard: close BTCB exposure'
            self.decision = reason
            if kind == 'HOLD':
                return
            if kind == 'BUY' and abs(m['BTCB']['price']/self.rows[-1]['close']-1) > .03:
                self.decision = 'Onchain price differs more than 3% from the hourly reference'
                return
            amount = min(20*UNIT, b['USDT']) if kind == 'BUY' else b['BTCB']
            if amount/UNIT*(1 if kind == 'BUY' else m['BTCB']['price']) < 5:
                self.decision = 'Order below the $5 minimum; manual dust recovery may be needed'
                return
            if b['BNB'] < m['gas_price']*600_000:
                self.decision = 'Insufficient BNB for approval and swap gas'
                return
        self.decision = reason
        if self.executor:
            self.executor.trade(kind, int(amount), m, reason)
        else:
            self.paper_fill(kind, int(amount), reason)

    def tick(self):
        market = self.chain.snapshot()
        rows = candles() if not self.rows or time.time()-self.last_candles > 60 else None
        with self.lock:
            self.market = market
            if rows is not None:
                self.rows, self.last_candles = rows, time.time()
                self.test = backtest(rows, market['gas_price']*180_000/UNIT*market['BNB']['price'])
            if time.time()-(self.rows[-1]['time']+3600) > 3900:
                raise RuntimeError('Candle reference is stale')
            self.initialize()
            if self.executor:
                self.executor.reconcile()
                if self.ledger.state['pending']:
                    self.decision = 'Waiting for three transaction confirmations'
                    return
                self.observed = self.chain.balances(self.executor.address)
                if self.observed != self.ledger.state['balances']:
                    self.ledger.state['pnl_valid'] = False
                    self.set_paused(True, 'Wallet changed outside the bot. P/L unavailable until the ledger is reconciled.')
                    return
            if time.time()-market['time'] > 30:
                raise RuntimeError('Snapshot expired during refresh; orders deferred')
            self.decide()
            self.error = ''

    def loop(self):
        while not self.stop_event.is_set():
            try:
                self.tick()
            except Exception as exc:
                with self.lock:
                    self.error = str(exc) if isinstance(exc, (RuntimeError, ValueError)) else type(exc).__name__+': operation failed; trading deferred'
            self.stop_event.wait(10)

    def start(self):
        self.worker.start()

    def set_paused(self, paused, reason='Manually paused'):
        with self.lock:
            s = self.ledger.state
            if not s:
                return
            if not paused and (s['loss_halt'] or not s['pnl_valid']):
                raise ValueError('Loss guard or ledger mismatch requires review; automatic resume disabled')
            s['paused'], s['pause_reason'] = paused, reason if paused else ''
            self.ledger.save()

    def snapshot(self):
        with self.lock:
            s = self.ledger.state
            if not self.market or not s:
                return {'ready': False, 'mode': self.mode.upper(), 'error': self.error}
            b = self.observed if self.executor and self.observed is not None else s['balances']
            value = equity(b, self.market)
            target, fast, slow = signal([r['close'] for r in self.rows])
            return {'ready': True, 'mode': self.mode.upper(), 'wallet': s['wallet'],
                'healthy': time.time()-self.market['time'] < 40 and not self.error,
                'error': self.error, 'paused': s['paused'], 'pause_reason': s['pause_reason'],
                'pending': s['pending'], 'decision': self.decision, 'market': self.market,
                'age': round(time.time()-self.market['time'], 1), 'balances': {k: v/UNIT for k, v in b.items()},
                'initial': s['initial'], 'equity': value, 'pnl': value-s['initial'] if s['pnl_valid'] else None,
                'realized': s['realized'] if s['pnl_valid'] else None,
                'entry': s['entry'], 'signal': target, 'fast': fast, 'slow': slow,
                'hold': s['initial']*self.market['BTCB']['price']/s['initial_btc_price'],
                'events': self.ledger.events(), 'candles': self.rows[-120:], 'backtest': self.test}
