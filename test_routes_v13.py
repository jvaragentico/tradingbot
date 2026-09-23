import copy
import threading
import time
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch
from eth_account import Account
from web3 import Web3

from arbitrage import ROUTES, make_candidate, scan_markets
from engine import TradingBot
from ledger import Ledger
from market import TOKENS, UNIT
from rpc import ReadFailoverProvider, batch_read
import test_bot as fixtures
from test_bot import market, state
from v3 import V3Markets, ROUTER_V3, ROUTER_V3_ABI, encode_path


class RouteTests(unittest.TestCase):
    def candidate(self, m=None):
        c = make_candidate(m or market(), ('USDT', 'BNB', 'USDT'), 20*UNIT, int(20.2*UNIT))
        c.update(venue='V3', fees=[100, 500])
        return c

    def executor(self):
        executor, ledger, eth, function = fixtures.ExecutionTests.setup_executor(self)
        token, router, quoter = Mock(), Mock(), Mock()
        token.functions.allowance.return_value.call.return_value = 20*UNIT
        quoter.functions.quoteExactInput.return_value.call.return_value = [int(20.2*UNIT)]
        v3 = SimpleNamespace(router=router, quoter=quoter, verify=Mock())
        executor.chain.v3, executor.chain.tokens = v3, {'USDT': token}
        return executor, token, router, quoter, eth

    def test_path_contains_two_distinct_pools_and_same_final_asset(self):
        path = encode_path(('USDT', 'BNB', 'USDT'), [100, 500])
        self.assertEqual(len(path), 66)
        self.assertEqual(path[:20], path[-20:])
        self.assertEqual(int.from_bytes(path[20:23], 'big'), 100)
        self.assertEqual(int.from_bytes(path[43:46], 'big'), 500)
        for route, fees in [(('USDT','BNB','USDT'),[100,100]),
                            (('USDT','BNB','BTCB'),[100,500]),
                            (('USDT','UNKNOWN','USDT'),[100,500]),
                            (('USDT','BNB','USDT'),[100,10000])]:
            with self.assertRaises(ValueError):
                encode_path(route, fees)

    def test_v3_order_uses_correct_router_recipient_and_profit_floor(self):
        executor, token, router, quoter, eth = self.executor()
        c = self.candidate()
        with patch.object(executor, 'submit', return_value='tx') as submit:
            executor.arbitrage(c, market())
        args = router.functions.exactInput.call_args.args[0]
        self.assertEqual(args[0], encode_path(c['route'], c['fees']))
        self.assertEqual(args[1], executor.address)
        self.assertGreater(args[4], args[3])
        self.assertEqual(token.functions.allowance.call_args.args[1], ROUTER_V3)
        self.assertEqual(submit.call_args.kwargs['metadata']['venue'], 'V3')

    def test_v3_approval_never_grants_v2_or_unlimited_allowance(self):
        executor, token, router, quoter, eth = self.executor()
        token.functions.allowance.return_value.call.return_value = 0
        with patch.object(executor, 'submit') as submit:
            executor.arbitrage(self.candidate(), market())
        self.assertEqual(token.functions.approve.call_args.args, (ROUTER_V3, 20*UNIT))
        self.assertEqual(submit.call_args.args[1], 'APPROVE')
        router.functions.exactInput.assert_not_called()

    def test_v3_expired_or_losing_quote_never_spends_approval(self):
        executor, token, router, quoter, eth = self.executor()
        token.functions.allowance.return_value.call.return_value = 0
        c = self.candidate()
        c['quoted_at'] -= 31
        with self.assertRaises(RuntimeError): executor.arbitrage(c, market())
        c['quoted_at'] = time.time()
        quoter.functions.quoteExactInput.return_value.call.return_value = [19*UNIT]
        with self.assertRaises(RuntimeError): executor.arbitrage(c, market())
        token.functions.approve.assert_not_called()
        eth.send_raw_transaction.assert_not_called()

    def test_v3_forged_profit_floor_or_route_rejected(self):
        executor, token, router, quoter, eth = self.executor()
        c = self.candidate()
        c['min_out'] = c['amount']
        with self.assertRaises(ValueError): executor.arbitrage(c, market())
        c = self.candidate()
        c['fees'] = [100,100]
        with self.assertRaises(ValueError): executor.arbitrage(c, market())
        eth.send_raw_transaction.assert_not_called()

    def test_real_v3_abi_encodes_and_signs_locally_without_network(self):
        w3, account = Web3(), Account.create()
        router = w3.eth.contract(address=ROUTER_V3, abi=ROUTER_V3_ABI)
        path = encode_path(('USDT','ETH','USDT'), [100,500])
        params = (path, account.address, int(time.time())+60, 20*UNIT, int(20.05*UNIT))
        tx = router.functions.exactInput(params).build_transaction({
            'from':account.address, 'nonce':0, 'chainId':56, 'gasPrice':50_000_000,'gas':300000})
        signed = account.sign_transaction(tx)
        self.assertEqual(Account.recover_transaction(signed.raw_transaction), account.address)
        fn, decoded = router.decode_function_input(tx['data'])
        self.assertEqual(fn.fn_name, 'exactInput')
        self.assertEqual(decoded['params']['path'], path)
        self.assertEqual(decoded['params']['amountOutMinimum'], params[-1])

    def test_v3_scanner_uses_exact_quote_after_pool_screen(self):
        v = V3Markets.__new__(V3Markets)
        v.verified = True
        v.pools = {('BNB',100):Mock(), ('BNB',500):Mock()}
        slot = lambda ratio: (int(ratio**.5*2**96), 0, 0, 0, 0, 0, True)
        values = [slot(.0014), (100000,), (100000*UNIT,),
                  slot(.00138), (100000,), (100000*UNIT,)]
        v.chain = SimpleNamespace(batch=Mock(side_effect=[values,
                                  [(int(5.05*UNIT),[],[],100000),
                                   (int(10.1*UNIT),[],[],100000),
                                   (int(20.2*UNIT),[],[],100000)]]), tokens={'USDT':Mock()})
        v.quoter = Mock()
        m = market(); m['block'] = 123
        result = v.scan(m, state()['balances'])
        self.assertEqual(result['candidate']['amount'], 20*UNIT)
        self.assertEqual(result['candidate']['fees'], [100,500])
        self.assertEqual(result['candidate']['block'], 123)
        for call in v.chain.batch.call_args_list:
            self.assertEqual(call.args[1], 123)

    def test_v3_identity_failure_blocks_usage(self):
        chain = SimpleNamespace(w3=Web3(), batch=Mock(return_value=[None]*4))
        with self.assertRaises(RuntimeError): V3Markets(chain).verify()

    def test_v2_failure_does_not_hide_valid_v3_candidate(self):
        m = market(); m['block'] = 1
        chain = SimpleNamespace(router=Mock(), batch=Mock(side_effect=RuntimeError('unavailable')))
        c = self.candidate(m)
        v3 = SimpleNamespace(scan=Mock(return_value={
            'best':c,'candidate':c,'quotes_checked':3,'errors':0}))
        result = scan_markets(chain, v3, m, state()['balances'])
        self.assertEqual(result['candidate']['venue'], 'V3')
        self.assertIn('error', result['venues']['V2'])


class DataTests(unittest.TestCase):
    def test_read_failover_checks_chain_and_never_rebroadcasts(self):
        p = ReadFailoverProvider(['https://first.invalid','https://second.invalid'])
        first, second = Mock(), Mock()
        first.make_request.side_effect = TimeoutError('timeout')
        second.make_request.side_effect = [{'result':'0x38'}, {'result':'0x123'}]
        p.providers = [first, second]
        self.assertEqual(p.make_request('eth_blockNumber', [])['result'], '0x123')
        self.assertEqual(p.current, 1)
        p.current = 0
        second.reset_mock()
        with self.assertRaises(TimeoutError): p.make_request('eth_sendRawTransaction',['signed'])
        second.make_request.assert_not_called()

    def test_wrong_chain_fallback_rejected(self):
        p = ReadFailoverProvider(['https://first.invalid','https://second.invalid'])
        a,b = Mock(),Mock()
        a.make_request.side_effect = TimeoutError()
        b.make_request.return_value = {'result':'0x1'}
        p.providers=[a,b]
        with self.assertRaises(RuntimeError): p.make_request('eth_call', [])

    def test_batch_pins_block_and_rejects_malformed_response(self):
        w3 = Mock()
        fn = Mock(address=TOKENS['USDT'], abi={'outputs':[{'type':'uint256'}]})
        w3.eth.contract.return_value.functions.aggregate3.return_value.call.return_value = []
        with self.assertRaises(RuntimeError): batch_read(w3,[fn],123)
        kwargs = w3.eth.contract.return_value.functions.aggregate3.return_value.call.call_args.kwargs
        self.assertEqual(kwargs['block_identifier'],123)

    def test_arbitrage_does_not_wait_for_candle_service(self):
        b = TradingBot.__new__(TradingBot)
        b.mode,b.executor,b.market='paper',None,market()
        b.market['block']=1
        b.lock,b.ledger=threading.RLock(),Ledger(':memory:')
        self.addCleanup(b.ledger.db.close)
        b.initialize()
        b.ledger.state['funded']=True
        b.ledger.state['balances']={'BNB':int(.001*UNIT),'USDT':21*UNIT,'BTCB':0}
        b.rows=[]; b.trend_entries=False; b.v3=Mock()
        b.chain=SimpleNamespace(snapshot=lambda:b.market)
        with patch('engine.candles',side_effect=RuntimeError()) as candles, patch(
            'engine.scan_markets',return_value={'candidate':None,'best':{},'errors':0}) as scan:
            b.tick()
        scan.assert_called_once()
        candles.assert_not_called()

    def test_stale_cached_candidate_is_not_executed(self):
        b = TradingBot.__new__(TradingBot)
        b.mode,b.executor,b.market='paper',None,market()
        b.lock,b.ledger=threading.RLock(),Ledger(':memory:')
        self.addCleanup(b.ledger.db.close)
        b.initialize()
        b.rows=[]; b.trend_entries=False
        b.ledger.state.update(funded=True)
        b.ledger.state['balances']={'BNB':int(.001*UNIT),'USDT':21*UNIT,'BTCB':0}
        candidate=make_candidate(b.market,('USDT','BTCB','BNB','USDT'),20*UNIT,21*UNIT)
        candidate['quoted_at']-=31
        b.arb_scan={'candidate':candidate}
        with patch.object(b,'paper_arb_fill') as fill: b.decide()
        fill.assert_not_called()

    def test_completed_position_count_is_not_fill_count(self):
        ledger=Ledger(':memory:'); self.addCleanup(ledger.db.close)
        for i,(kind,delta,fee) in enumerate([('APPROVE',0,.01),('BUY',-20,.01),
                                            ('APPROVE',0,.01),('SELL',19.6,.01)]):
            ledger.save({'txid':str(i),'kind':kind,'deltas':{'USDT':int(delta*UNIT)},'gas_usd':fee})
        result=ledger.performance()
        self.assertEqual(result['closed_positions'],1)
        self.assertEqual(result['winning_positions'],0)
        self.assertAlmostEqual(result['closed_position_pnl_usd'],-.44)


if __name__ == '__main__':
    unittest.main()
