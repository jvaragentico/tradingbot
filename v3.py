"""Atomic USDT round trips between distinct PancakeSwap V3 fee-tier pools."""
import itertools
import time
from web3 import Web3
from market import TOKENS, UNIT, abi_function

ROUTER_V3 = Web3.to_checksum_address('0x1b81D678ffb9C0263b24A97847620C99d213eB14')
FACTORY_V3 = Web3.to_checksum_address('0x0BFbCF9fa4f9C56B0F40a671Ad40E0805A091865')
QUOTER_V3 = Web3.to_checksum_address('0xB048Bbc1Ee6b733FFfCFb9e9CeF7375518e25997')
FEE_TIERS = (100, 500, 2500)  # hundredths of a basis point: 0.01%, 0.05%, 0.25%
MID_ASSETS = ('BNB', 'BTCB', 'ETH', 'USDC', 'CAKE')
IDENTITY_ABI = [abi_function('factory', [], ['address']), abi_function('WETH9', [], ['address'])]
QUOTER_ABI = IDENTITY_ABI + [abi_function('quoteExactInput', ['bytes', 'uint256'],
                                    ['uint256', 'uint160[]', 'uint32[]', 'uint256'], 'nonpayable')]
ROUTER_V3_ABI = IDENTITY_ABI + [{
    'type': 'function', 'name': 'exactInput', 'stateMutability': 'payable',
    'inputs': [{'name': 'params', 'type': 'tuple', 'components': [
        {'name': 'path', 'type': 'bytes'}, {'name': 'recipient', 'type': 'address'},
        {'name': 'deadline', 'type': 'uint256'}, {'name': 'amountIn', 'type': 'uint256'},
        {'name': 'amountOutMinimum', 'type': 'uint256'}]}],
    'outputs': [{'name': 'amountOut', 'type': 'uint256'}]}]
POOL_ABI = [abi_function('slot0', [], ['uint160', 'int24', 'uint16', 'uint16', 'uint16', 'uint32', 'bool']),
            abi_function('liquidity', [], ['uint128'])]


def encode_path(route, fees):
    if (len(route) != 3 or route[0] != 'USDT' or route[-1] != 'USDT'
            or route[1] not in MID_ASSETS or len(fees) != 2 or fees[0] == fees[1]
            or any(f not in FEE_TIERS for f in fees)):
        raise ValueError('Unapproved V3 round-trip route')
    return (bytes.fromhex(TOKENS[route[0]][2:]) + int(fees[0]).to_bytes(3, 'big')
            + bytes.fromhex(TOKENS[route[1]][2:]) + int(fees[1]).to_bytes(3, 'big')
            + bytes.fromhex(TOKENS[route[2]][2:]))


class V3Markets:
    def __init__(self, chain):
        self.chain = chain
        self.router = chain.w3.eth.contract(address=ROUTER_V3, abi=ROUTER_V3_ABI)
        self.quoter = chain.w3.eth.contract(address=QUOTER_V3, abi=QUOTER_ABI)
        self.factory = chain.w3.eth.contract(address=FACTORY_V3,
            abi=[abi_function('getPool', ['address', 'address', 'uint24'], ['address'])])
        self.pools, self.verified = {}, False

    def verify(self):
        if self.verified:
            return
        expected = (FACTORY_V3.lower(), TOKENS['BNB'].lower())*2
        functions = [c.functions.factory() for c in (self.router,)] + [self.router.functions.WETH9(),
                     self.quoter.functions.factory(), self.quoter.functions.WETH9()]
        values = self.chain.batch(functions)
        if tuple(v[0].lower() if v else '' for v in values) != expected:
            raise RuntimeError('V3 router/quoter identity check failed')
        keys = list(itertools.product(MID_ASSETS, FEE_TIERS))
        found = self.chain.batch([self.factory.functions.getPool(TOKENS['USDT'], TOKENS[a], fee)
                                  for a, fee in keys])
        for key, value in zip(keys, found):
            if value and int(value[0], 16):
                self.pools[key] = self.chain.w3.eth.contract(address=Web3.to_checksum_address(value[0]), abi=POOL_ABI)
        self.verified = True

    def scan(self, market, balances, approval_cost=0):
        from arbitrage import make_candidate, summarize
        self.verify()
        if balances['USDT'] < 5*UNIT:
            return summarize([], 0, 0, venue='V3', pools=len(self.pools), pairs=[])
        functions = []
        for pool in self.pools.values():
            functions.extend([pool.functions.slot0(), pool.functions.liquidity(),
                              self.chain.tokens['USDT'].functions.balanceOf(pool.address)])
        values = self.chain.batch(functions, market['block'])
        prices, errors = {}, 0
        for i, ((asset, fee), pool) in enumerate(self.pools.items()):
            slot, liquidity, quote_balance = values[i*3:i*3+3]
            if not slot or not liquidity or not quote_balance:
                errors += 1
                continue
            if not slot[-1] or not slot[0] or not liquidity[0] or quote_balance[0] < 50_000*UNIT:
                continue
            ratio = (slot[0]/(2**96))**2
            # All allowlisted tokens have 18 decimals; ratio is token1/token0.
            prices[(asset, fee)] = ratio if int(TOKENS['USDT'], 16) < int(TOKENS[asset], 16) else 1/ratio
        maximum = min(balances['USDT'], 20*UNIT)
        # Screen by the no-impact upper bound; exact quotes still decide execution.
        ranked = []
        for asset in MID_ASSETS:
            for first, second in itertools.permutations(FEE_TIERS, 2):
                if (asset, first) not in prices or (asset, second) not in prices:
                    continue
                ratio = prices[(asset, first)]/prices[(asset, second)]*(1-first/1e6)*(1-second/1e6)
                ranked.append((ratio, ('USDT', asset, 'USDT'), (first, second)))
        ranked.sort(reverse=True)
        # Quote the best route even when negative so the dashboard explains inactivity.
        selected = [r for r in ranked[:8] if r[0] > 1] or ranked[:1]
        jobs = [(route, fees, amount) for _, route, fees in selected
                for amount in sorted({min(maximum, 5*UNIT), min(maximum, 10*UNIT), maximum})]
        if time.time()-market['time'] > 20:
            raise RuntimeError('V3 scan snapshot expired')
        # Bound quoter work per call. All chunks are pinned to the same block.
        candidates, checked = [], 0
        for start in range(0, len(jobs), 8):
            if time.time()-market['time'] > 22:
                errors += len(jobs)-start
                break
            chunk = jobs[start:start+8]
            quoted = self.chain.batch([self.quoter.functions.quoteExactInput(encode_path(r, f), a)
                                       for r, f, a in chunk], market['block'])
            for (route, fees, amount), value in zip(chunk, quoted):
                checked += 1
                if not value:
                    errors += 1
                    continue
                c = make_candidate(market, route, amount, value[0], approval_cost)
                c.update(venue='V3', fees=list(fees), pool_fee_pct=sum(fees)/10000)
                candidates.append(c)
        return summarize(candidates, errors, checked, venue='V3', pools=len(prices),
                         routes_screened=len(ranked), pairs=sorted({a for a, f in prices}))
