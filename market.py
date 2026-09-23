"""Public market data and allowlisted PancakeSwap V2 contracts."""
import json
import os
import time
import urllib.request

from web3 import Web3
from web3.middleware import ExtraDataToPOAMiddleware

RPC_URL = os.environ.get('BSC_RPC_URL', 'https://bsc-dataseed.bnbchain.org')
ROUTER = Web3.to_checksum_address('0x10ed43c718714eb63d5aa57b78b54704e256024e')
FACTORY = Web3.to_checksum_address('0xca143ce32fe78f1f7019d7d551a6402fc5350c73')
TOKENS = {k: Web3.to_checksum_address(v) for k, v in {
    'BTCB': '0x7130d2a12b9bcbfae4f2634d864a1ee1ce3ead9c',
    'USDT': '0x55d398326f99059ff775485246999027b3197955',
    'BNB': '0xbb4cdb9cbd36b01bd1cbaebf2de08d9173bc095c',
}.items()}
UNIT = 10**18


def abi_function(name, inputs, outputs, state='view'):
    return {'type': 'function', 'name': name, 'stateMutability': state,
            'inputs': [{'name': f'a{i}', 'type': t} for i, t in enumerate(inputs)],
            'outputs': [{'name': f'r{i}', 'type': t} for i, t in enumerate(outputs)]}


TOKEN_ABI = [abi_function('decimals', [], ['uint8']),
             abi_function('balanceOf', ['address'], ['uint256']),
             abi_function('allowance', ['address', 'address'], ['uint256']),
             abi_function('approve', ['address', 'uint256'], ['bool'], 'nonpayable')]
ROUTER_ABI = [abi_function('factory', [], ['address']), abi_function('WETH', [], ['address']),
              abi_function('getAmountsOut', ['uint256', 'address[]'], ['uint256[]']),
              abi_function('swapExactETHForTokens', ['uint256', 'address[]', 'address', 'uint256'], ['uint256[]'], 'payable'),
              abi_function('swapExactTokensForTokens', ['uint256', 'uint256', 'address[]', 'address', 'uint256'], ['uint256[]'], 'nonpayable')]
PAIR_ABI = [abi_function('token0', [], ['address']), abi_function('token1', [], ['address']),
            abi_function('getReserves', [], ['uint112', 'uint112', 'uint32'])]


class Chain:
    def __init__(self):
        self.w3 = Web3(Web3.HTTPProvider(RPC_URL, request_kwargs={'timeout': 12}))
        self.w3.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)
        self.router = self.w3.eth.contract(address=ROUTER, abi=ROUTER_ABI)
        self.tokens = {k: self.w3.eth.contract(address=v, abi=TOKEN_ABI) for k, v in TOKENS.items()}
        self.pools = {}
        self.checked = False

    def verify(self):
        if self.checked:
            return
        if self.w3.eth.chain_id != 56:
            raise RuntimeError('Wrong network: expected BNB Smart Chain 56')
        if self.router.functions.factory().call() != FACTORY or self.router.functions.WETH().call() != TOKENS['BNB']:
            raise RuntimeError('Router identity check failed')
        factory = self.w3.eth.contract(address=FACTORY, abi=[abi_function('getPair', ['address', 'address'], ['address'])])
        for symbol in ('BTCB', 'BNB'):
            address = factory.functions.getPair(TOKENS[symbol], TOKENS['USDT']).call()
            if int(address, 16) == 0:
                raise RuntimeError('Required pool is unavailable')
            pair = self.w3.eth.contract(address=address, abi=PAIR_ABI)
            token0, token1 = pair.functions.token0().call(), pair.functions.token1().call()
            if {token0, token1} != {TOKENS[symbol], TOKENS['USDT']}:
                raise RuntimeError('Pool token mismatch')
            self.pools[symbol] = (pair, token0 == TOKENS[symbol])
        if any(token.functions.decimals().call() != 18 for token in self.tokens.values()):
            raise RuntimeError('Unexpected token decimals')
        self.checked = True

    def snapshot(self):
        self.verify()
        block = self.w3.eth.get_block('latest')
        if not -10 <= time.time() - block['timestamp'] <= 45:
            raise RuntimeError('RPC block is stale or local clock is wrong')
        result = {'time': time.time(), 'block': block['number'], 'block_time': block['timestamp'],
                  'gas_price': self.w3.eth.gas_price}
        for symbol, (pair, base_first) in self.pools.items():
            a, b, _ = pair.functions.getReserves().call(block_identifier=block['number'])
            base, quote = (a, b) if base_first else (b, a)
            if not base or quote / UNIT < 50_000:
                raise RuntimeError('Pool liquidity below the $100,000 safety floor')
            result[symbol] = {'price': quote / base, 'base_reserve': base, 'quote_reserve': quote, 'pool': pair.address}
        return result

    def balances(self, address):
        block = self.w3.eth.block_number
        return {'BNB': self.w3.eth.get_balance(address, block),
                'USDT': self.tokens['USDT'].functions.balanceOf(address).call(block_identifier=block),
                'BTCB': self.tokens['BTCB'].functions.balanceOf(address).call(block_identifier=block)}


def candles():
    req = urllib.request.Request('https://api.kraken.com/0/public/OHLC?pair=XBTUSD&interval=60', headers={'User-Agent': 'OrbitBot/1.0'})
    with urllib.request.urlopen(req, timeout=12) as response:
        data = json.load(response)
    if data['error']:
        raise RuntimeError('Kraken market data error')
    rows = next(v for k, v in data['result'].items() if k != 'last')
    # Kraken always includes the unfinished candle; never feed it into the strategy.
    result = [{'time': int(r[0]), 'open': float(r[1]), 'close': float(r[4])}
              for r in rows[:-1] if int(r[0]) + 3600 <= time.time()]
    if len(result) < 51 or time.time() - (result[-1]['time'] + 3600) > 3900:
        raise RuntimeError('Historical market data is stale or incomplete')
    return result


def amount_out(amount, reserve_in, reserve_out):
    """PancakeSwap V2 exact integer quote, including 0.25% pool fee."""
    if amount <= 0 or reserve_in <= 0 or reserve_out <= 0:
        return 0
    adjusted = amount * 9975
    return adjusted * reserve_out // (reserve_in * 10000 + adjusted)


def equity(balances, market):
    return (balances['USDT'] + balances['BNB'] * market['BNB']['price'] + balances['BTCB'] * market['BTCB']['price']) / UNIT
