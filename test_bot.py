import copy
import threading
import time
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from eth_account import Account
from hexbytes import HexBytes
from web3 import Web3
from arbitrage import ROUTES, scan
from engine import TradingBot
from execution import LiveExecutor, TRANSFER, transfer_deltas
from ledger import Ledger, apply_event
from market import UNIT, TOKENS, ROUTER, ROUTER_ABI, amount_out
from strategy import action, backtest, signal


def market():
    return {'time': time.time(), 'gas_price': 50_000_000,
        'BNB': {'price': 800, 'base_reserve': 50_000*UNIT, 'quote_reserve': 40_000_000*UNIT},
        'BTCB': {'price': 100_000, 'base_reserve': 100*UNIT, 'quote_reserve': 10_000_000*UNIT}}


def state():
    return {'balances': {'BNB': int(.001*UNIT), 'USDT': 22*UNIT, 'BTCB': 0},
        'cost': 0., 'entry': 0., 'realized': 0., 'pending': None, 'paused': False,
        'pause_reason': '', 'funded': True, 'last_trade': 0}


def transfer(token, sender, recipient, amount):
    return {'address': TOKENS[token], 'topics': [TRANSFER, HexBytes('0x'+sender[2:].rjust(64, '0')),
        HexBytes('0x'+recipient[2:].rjust(64, '0'))], 'data': HexBytes(amount.to_bytes(32, 'big'))}


class StrategyTests(unittest.TestCase):
    def test_warmup_and_flat(self):
        self.assertEqual(signal([100]*49)[0], 'WAIT')
        self.assertEqual(signal([100]*50)[0], 'HOLD')

    def test_direction(self):
        self.assertEqual(signal(list(range(1, 101)))[0], 'BUY')
        self.assertEqual(signal(list(range(101, 1, -1)))[0], 'SELL')

    def test_risk_exit_bypasses_cooldown_and_daily_limit(self):
        result = action([100]*60, True, 97, 100, 1000, 1001, 10)
        self.assertEqual(result[0], 'SELL')

    def test_cooldown_blocks_entry(self):
        self.assertEqual(action(list(range(100)), False, 100, 0, 1000, 1001, 0)[0], 'HOLD')

    def test_backtest_cannot_see_future_close(self):
        rows = [{'time': i*3600, 'open': 100, 'close': 100} for i in range(60)]
        rows[50]['close'] = 200
        result = backtest(rows, .01)
        buys = [t for t in result['trades'] if t['side'] == 'BUY']
        self.assertTrue(buys)
        self.assertGreaterEqual(buys[0]['time'], rows[51]['time'])
        self.assertEqual(buys[0]['price'], 100)

    def test_fees_prevent_free_roundtrip_profit(self):
        got = amount_out(20*UNIT, 1_000_000*UNIT, 10*UNIT)
        back = amount_out(got, 10*UNIT, 1_000_000*UNIT)
        self.assertLess(back, 20*UNIT)


class PaperTests(unittest.TestCase):
    def bot(self):
        b = TradingBot.__new__(TradingBot)
        b.mode, b.executor, b.market = 'paper', None, market()
        b.ledger, b.lock = Ledger(':memory:'), threading.RLock()
        self.addCleanup(b.ledger.db.close)
        b.initialize()
        return b

    def test_capital_funding_then_buy_and_sell(self):
        b = self.bot()
        initial = copy.deepcopy(b.ledger.state['balances'])
        b.paper_fill('FUND', initial['BNB']-int(.0003*UNIT), 'fund')
        self.assertTrue(b.ledger.state['funded'])
        self.assertGreater(b.ledger.state['balances']['USDT'], 20*UNIT)
        b.paper_fill('BUY', 20*UNIT, 'entry')
        qty = b.ledger.state['balances']['BTCB']
        self.assertGreater(qty, 0)
        b.paper_fill('SELL', qty, 'exit')
        self.assertEqual(b.ledger.state['balances']['BTCB'], 0)
        self.assertLess(b.ledger.state['realized'], 0)
        self.assertEqual([e['kind'] for e in b.ledger.events()], ['SELL', 'BUY', 'FUND'])

    def test_drawdown_halts_new_entries(self):
        b = self.bot()
        b.ledger.state['balances'] = {'BNB': int(.0001*UNIT), 'BTCB': 0, 'USDT': 19*UNIT}
        b.decide()
        self.assertTrue(b.ledger.state['paused'])
        self.assertTrue(b.ledger.state['loss_halt'])
        with self.assertRaises(ValueError):
            b.set_paused(False)

    def test_pause_prevents_execution(self):
        b = self.bot()
        b.set_paused(True)
        b.decide()
        self.assertEqual(b.ledger.events(), [])

    def test_funding_caps_wallet_above_22_to_22_invested(self):
        b = self.bot()
        b.ledger.state['balances'] = {'BNB': int(22.78 / 800 * UNIT), 'BTCB': 0, 'USDT': 0}
        b.ledger.state['initial'] = 22.78
        b.decide()
        fund = b.ledger.events()[0]
        self.assertLessEqual(-fund['deltas']['BNB'] / UNIT * 800, 22.02)
        self.assertGreater(b.ledger.state['balances']['BNB'] / UNIT * 800, .7)

    def test_profitable_paper_triangle_updates_owned_token_and_gas(self):
        b = self.bot()
        b.ledger.state['funded'] = True
        b.ledger.state['balances'] = {'BNB': int(.001*UNIT), 'BTCB': 0, 'USDT': 20*UNIT}
        candidate = scan(b.market, b.ledger.state['balances'],
                         lambda route, amount: amount + int(.20*UNIT))['candidate']
        self.assertIsNotNone(candidate)
        b.paper_arb_fill(candidate)
        self.assertEqual(b.ledger.events()[0]['kind'], 'ARB')
        self.assertGreater(b.ledger.state['balances']['USDT'], 20*UNIT)
        self.assertLess(b.ledger.state['balances']['BNB'], int(.001*UNIT))


class ArbitrageTests(unittest.TestCase):
    def test_pool_fees_and_gas_block_negative_round_trip(self):
        balances = {'BNB': int(.001*UNIT), 'BTCB': 0, 'USDT': 20*UNIT}
        result = scan(market(), balances, lambda route, amount: int(amount*.995))
        self.assertIsNone(result['candidate'])
        self.assertLess(result['best']['gross_gain_usd'], 0)

    def test_only_same_asset_routes_with_net_gain_qualify(self):
        balances = {'BNB': int(.001*UNIT), 'BTCB': 0, 'USDT': 20*UNIT}
        result = scan(market(), balances, lambda route, amount: amount+int(.20*UNIT))
        candidate = result['candidate']
        self.assertIn(tuple(candidate['route']), ROUTES)
        self.assertEqual(candidate['route'][0], candidate['route'][-1])
        self.assertGreater(candidate['min_out'], candidate['amount'])
        self.assertLess(candidate['min_out'], candidate['quoted_out'])


class ExecutionTests(unittest.TestCase):
    def setup_executor(self):
        ledger = Ledger(':memory:')
        self.addCleanup(ledger.db.close)
        ledger.state = state()
        account = Account.create()
        eth = SimpleNamespace(chain_id=56, gas_price=50_000_000, block_number=102,
            get_transaction_count=Mock(return_value=0),
            send_raw_transaction=Mock(side_effect=lambda raw: Web3.keccak(raw)))
        chain = SimpleNamespace(w3=SimpleNamespace(eth=eth), balances=Mock(side_effect=lambda address: ledger.state['balances']))
        executor = LiveExecutor(chain, ledger, account.key)
        function = Mock()
        function.estimate_gas.return_value = 100_000
        function.build_transaction.side_effect = lambda params: {**params, 'to': ROUTER, 'data': '0x'}
        return executor, ledger, eth, function

    def test_broadcast_timeout_preserves_intent_and_blocks_duplicate(self):
        executor, ledger, eth, function = self.setup_executor()
        eth.send_raw_transaction.side_effect = TimeoutError()
        with self.assertRaises(RuntimeError):
            executor.submit(function, 'BUY', market())
        self.assertTrue(ledger.state['pending']['txid'].startswith('0x'))
        saved = ledger.db.execute('SELECT data FROM portfolio').fetchone()[0]
        self.assertIn(ledger.state['pending']['txid'], saved)
        with self.assertRaises(RuntimeError):
            executor.submit(function, 'BUY', market())
        self.assertEqual(eth.send_raw_transaction.call_count, 1)

    def test_confirmed_fill_updates_once(self):
        executor, ledger, eth, function = self.setup_executor()
        executor.submit(function, 'BUY', market())
        receipt = {'status': 1, 'blockNumber': 100, 'gasUsed': 100_000, 'effectiveGasPrice': 50_000_000,
            'logs': [transfer('USDT', executor.address, ROUTER, 20*UNIT),
                     transfer('BTCB', ROUTER, executor.address, 200_000_000_000_000)]}
        eth.get_transaction_receipt = Mock(return_value=receipt)
        executor.reconcile()
        self.assertEqual(ledger.state['balances']['USDT'], 2*UNIT)
        self.assertEqual(ledger.state['balances']['BTCB'], 200_000_000_000_000)
        self.assertIsNone(ledger.state['pending'])
        executor.reconcile()
        self.assertEqual(len(ledger.events()), 1)

    def test_atomic_triangle_receipt_accounts_for_net_usdt(self):
        executor, ledger, eth, function = self.setup_executor()
        executor.submit(function, 'ARB', market(), metadata={'arb_asset': 'USDT', 'asset_price': 1.0})
        receipt = {'status': 1, 'blockNumber': 100, 'gasUsed': 100_000,
            'effectiveGasPrice': 50_000_000,
            'logs': [transfer('USDT', executor.address, ROUTER, 20*UNIT),
                     transfer('USDT', ROUTER, executor.address, int(20.2*UNIT))]}
        eth.get_transaction_receipt = Mock(return_value=receipt)
        executor.reconcile()
        self.assertAlmostEqual(ledger.state['balances']['USDT']/UNIT, 22.2, places=6)
        self.assertGreater(ledger.state['realized'], 0)
        self.assertEqual(ledger.events()[0]['kind'], 'ARB')

    def test_triangle_refuses_moved_quote_before_broadcast(self):
        executor, ledger, eth, function = self.setup_executor()
        token = Mock()
        token.functions.allowance.return_value.call.return_value = 20*UNIT
        executor.chain.tokens = {'USDT': token}
        router = Mock()
        router.functions.getAmountsOut.return_value.call.return_value = [20*UNIT, 0, 0, 20*UNIT]
        executor.chain.router = router
        candidate = scan(market(), ledger.state['balances'],
                         lambda route, amount: amount+int(.20*UNIT))['candidate']
        with self.assertRaises(RuntimeError):
            executor.arbitrage(candidate, market())
        eth.send_raw_transaction.assert_not_called()

    def test_triangle_builds_one_atomic_four_token_path(self):
        executor, ledger, eth, function = self.setup_executor()
        token = Mock()
        token.functions.allowance.return_value.call.return_value = 20*UNIT
        executor.chain.tokens = {'USDT': token}
        router = Mock()
        router.functions.getAmountsOut.return_value.call.return_value = [20*UNIT, 0, 0, 20*UNIT+int(.2*UNIT)]
        executor.chain.router = router
        candidate = scan(market(), ledger.state['balances'],
                         lambda route, amount: amount+int(.2*UNIT))['candidate']
        with patch.object(executor, 'submit', return_value='tx') as submit:
            self.assertEqual(executor.arbitrage(candidate, market()), 'tx')
        args = router.functions.swapExactTokensForTokens.call_args.args
        self.assertEqual(len(args[2]), 4)
        self.assertEqual(args[2][0], args[2][-1])
        self.assertGreater(args[1], args[0])
        self.assertEqual(submit.call_args.args[1], 'ARB')

    def test_reverted_transaction_charges_gas_and_pauses(self):
        executor, ledger, eth, function = self.setup_executor()
        before = ledger.state['balances']['BNB']
        executor.submit(function, 'FUND', market(), value=100)
        eth.get_transaction_receipt = Mock(return_value={'status': 0, 'blockNumber': 100,
            'gasUsed': 100_000, 'effectiveGasPrice': 50_000_000, 'logs': []})
        executor.reconcile()
        self.assertEqual(ledger.state['balances']['BNB'], before-100_000*50_000_000)
        self.assertTrue(ledger.state['paused'])
        self.assertEqual(ledger.events()[0]['kind'], 'FAILED')

    def test_wrong_chain_gas_cap_and_order_cap(self):
        executor, ledger, eth, function = self.setup_executor()
        eth.chain_id = 1
        with self.assertRaises(RuntimeError): executor.submit(function, 'BUY', market())
        eth.chain_id, eth.gas_price = 56, 2_000_000_000
        with self.assertRaises(RuntimeError): executor.submit(function, 'BUY', market())
        with self.assertRaises(RuntimeError): executor.trade('BUY', 21*UNIT, market(), 'test')
        eth.send_raw_transaction.assert_not_called()

    def test_three_confirmations_required(self):
        executor, ledger, eth, function = self.setup_executor()
        executor.submit(function, 'APPROVE', market())
        eth.get_transaction_receipt = Mock(return_value={'blockNumber': 102})
        self.assertIsNone(executor.reconcile())
        self.assertIsNotNone(ledger.state['pending'])

    def test_external_wallet_change_blocks_submission(self):
        executor, ledger, eth, function = self.setup_executor()
        executor.chain.balances.side_effect = lambda address: {'BNB': 1, 'BTCB': 0, 'USDT': 0}
        with self.assertRaises(RuntimeError): executor.submit(function, 'BUY', market())
        eth.send_raw_transaction.assert_not_called()

    def test_stale_market_blocks_submission(self):
        executor, ledger, eth, function = self.setup_executor()
        old = market()
        old['time'] -= 60
        with self.assertRaises(RuntimeError): executor.submit(function, 'BUY', old)
        eth.send_raw_transaction.assert_not_called()

    def test_duplicate_server_cannot_start_an_order_worker(self):
        import app
        worker = Mock()
        with patch.object(app, 'LocalServer', side_effect=OSError('port in use')):
            with self.assertRaises(OSError): app.serve(worker)
        worker.start.assert_not_called()

    def test_clipboard_key_is_cleared_and_seed_words_rejected(self):
        import app
        import sys
        key = '0x' + '1' * 64
        root = Mock()
        root.clipboard_get.return_value = key
        fake_tk = SimpleNamespace(Tk=Mock(return_value=root), TclError=Exception)
        with patch.object(app.os, 'name', 'nt'), patch('builtins.input'), patch.dict(sys.modules, {'tkinter': fake_tk}):
            self.assertEqual(app.key_from_clipboard(), key)
            root.clipboard_get.return_value = 'twelve seed words are not an account private key'
            with self.assertRaises(RuntimeError):
                app.key_from_clipboard()
        self.assertEqual(root.clipboard_clear.call_count, 2)

    def test_router_abi_and_local_signature(self):
        w3 = Web3()
        router = w3.eth.contract(address=ROUTER, abi=ROUTER_ABI)
        account = Account.create()
        fn = router.functions.swapExactTokensForTokens(20*UNIT, 1, [TOKENS['USDT'], TOKENS['BTCB']], account.address, 2_000_000_000)
        tx = fn.build_transaction({'from': account.address, 'chainId': 56, 'gasPrice': 50_000_000, 'gas': 200_000, 'nonce': 0})
        signed = account.sign_transaction(tx)
        self.assertEqual(Account.recover_transaction(signed.raw_transaction), account.address)
        decoded, args = router.decode_function_input(tx['data'])
        self.assertEqual(decoded.fn_name, 'swapExactTokensForTokens')
        self.assertEqual(args['a0'], 20*UNIT)


if __name__ == '__main__':
    unittest.main()
