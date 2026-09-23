"""Real, locally signed PancakeSwap orders, with a durable transaction journal."""
import copy
import time

from eth_account import Account
from web3 import Web3
from web3.exceptions import TransactionNotFound

from ledger import apply_event
from market import ROUTER, TOKENS, UNIT

TRANSFER = Web3.keccak(text='Transfer(address,address,uint256)')
SLIPPAGE_BPS = 50
MAX_ORDER_USD = 20
MAX_GAS_USD = .15
MAX_GAS_PRICE = 1_000_000_000


def transfer_deltas(receipt, address):
    """Read actual ERC20 amounts from receipt logs, rather than treating a quote as a fill."""
    deltas = {'BNB': 0, 'BTCB': 0, 'USDT': 0}
    wallet = address.lower()[2:].rjust(64, '0')
    symbols = {v.lower(): k for k, v in TOKENS.items() if k != 'BNB'}
    for log in receipt['logs']:
        symbol = symbols.get(log['address'].lower())
        topics = log['topics']
        if not symbol or len(topics) != 3 or bytes(topics[0]) != bytes(TRANSFER):
            continue
        amount = int.from_bytes(bytes(log['data']), 'big')
        if bytes(topics[1]).hex() == wallet:
            deltas[symbol] -= amount
        if bytes(topics[2]).hex() == wallet:
            deltas[symbol] += amount
    return deltas


class LiveExecutor:
    def __init__(self, chain, ledger, private_key):
        self.chain, self.ledger = chain, ledger
        self.account = Account.from_key(private_key)
        self.address = self.account.address

    def submit(self, function, kind, market, value=0, reason=''):
        state, w3 = self.ledger.state, self.chain.w3
        if state.get('pending'):
            raise RuntimeError('An unresolved transaction already exists')
        if time.time() - market['time'] > 30:
            raise RuntimeError('Market snapshot expired before order preparation')
        if state.get('paused') and kind != 'SELL':
            raise RuntimeError('Trading is paused')
        if w3.eth.chain_id != 56:
            raise RuntimeError('Wrong chain')
        if self.chain.balances(self.address) != state['balances']:
            raise RuntimeError('Wallet changed outside the bot; reconcile before trading')
        nonce = w3.eth.get_transaction_count(self.address, 'pending')
        if nonce != w3.eth.get_transaction_count(self.address, 'latest'):
            raise RuntimeError('Wallet has an external pending transaction')
        gas_price = w3.eth.gas_price
        if gas_price > MAX_GAS_PRICE:
            raise RuntimeError('Gas price exceeds 1 gwei limit')
        params = {'from': self.address, 'value': value, 'nonce': nonce, 'chainId': 56, 'gasPrice': gas_price}
        gas_limit = int(function.estimate_gas(params) * 1.25)
        gas_cap = gas_limit * gas_price
        if gas_cap / UNIT * market['BNB']['price'] > MAX_GAS_USD:
            raise RuntimeError('Transaction gas budget exceeds $0.15')
        if state['balances']['BNB'] < value + gas_cap:
            raise RuntimeError('Insufficient native BNB for transaction gas')
        transaction = function.build_transaction({**params, 'gas': gas_limit})
        signed = self.account.sign_transaction(transaction)
        txid = Web3.to_hex(signed.hash)
        state['pending'] = {'txid': txid, 'kind': kind, 'value': value, 'reason': reason,
                            'time': time.time(), 'bnb_price': market['BNB']['price'], 'nonce': nonce}
        self.ledger.save()  # durable intent before broadcast: never blindly retry a timed-out order
        try:
            returned = Web3.to_hex(w3.eth.send_raw_transaction(signed.raw_transaction))
            if returned.lower() != txid.lower():
                raise RuntimeError('RPC returned a different transaction hash')
        except Exception:
            state['paused'] = True
            state['pause_reason'] = 'Broadcast outcome uncertain. Waiting for the recorded transaction; no replacement order will be sent.'
            self.ledger.save()
            raise RuntimeError(state['pause_reason']) from None
        return txid

    def reconcile(self):
        state, w3 = self.ledger.state, self.chain.w3
        pending = state.get('pending')
        if not pending:
            return None
        try:
            receipt = w3.eth.get_transaction_receipt(pending['txid'])
        except TransactionNotFound:
            if time.time() - pending['time'] > 180:
                state['paused'] = True
                state['pause_reason'] = 'Pending transaction needs review on BscScan. Automatic resubmission is disabled.'
                self.ledger.save()
            return None
        if w3.eth.block_number - receipt['blockNumber'] < 2:
            return None  # three confirmations before applying fills
        gas_bnb = int(receipt['gasUsed']) * int(receipt['effectiveGasPrice'])
        deltas = transfer_deltas(receipt, self.address)
        deltas['BNB'] = -gas_bnb - (pending['value'] if receipt['status'] == 1 else 0)
        kind = pending['kind'] if receipt['status'] == 1 else 'FAILED'
        event = {'txid': pending['txid'], 'kind': kind, 'time': pending['time'], 'deltas': deltas,
                 'gas_usd': gas_bnb / UNIT * pending['bnb_price'], 'reason': pending['reason'],
                 'block': receipt['blockNumber'], 'execution': 'LIVE'}
        event['funding_usd'] = pending['value']/UNIT*pending['bnb_price'] if kind == 'FUND' else 0
        updated = copy.deepcopy(state)
        apply_event(updated, event)
        if kind == 'FAILED':
            updated['paused'] = True
            updated['pause_reason'] = 'Transaction reverted; gas was charged. Review before resuming.'
        self.ledger.state = updated
        self.ledger.save(event)
        return event

    def trade(self, kind, amount, market, reason):
        if kind not in ('FUND', 'BUY', 'SELL') or amount <= 0:
            raise ValueError('Invalid trade request')
        source = 'BNB' if kind == 'FUND' else 'USDT' if kind == 'BUY' else 'BTCB'
        target = 'BTCB' if kind == 'BUY' else 'USDT'
        price = 1 if source == 'USDT' else market[source]['price']
        limit = 22 if kind == 'FUND' else MAX_ORDER_USD if kind == 'BUY' else float('inf')
        # SELL may close an appreciated position; it never sells more than the owned bot balance.
        if amount > self.ledger.state['balances'][source] or amount / UNIT * price > limit + 1e-8:
            raise RuntimeError('Trade exceeds the owned balance or funding/order cap')
        if source != 'BNB':
            token = self.chain.tokens[source]
            allowance = token.functions.allowance(self.address, ROUTER).call()
            if allowance < amount:
                # Exact allowance, never unlimited; approval and swap are separately journaled.
                return self.submit(token.functions.approve(ROUTER, amount), 'APPROVE', market, reason=f'Approve exact {source} amount')
        path = [TOKENS[source], TOKENS[target]]
        quote = self.chain.router.functions.getAmountsOut(amount, path).call()[-1]
        target_price = market['BTCB']['price'] if target == 'BTCB' else 1
        if quote / UNIT * target_price < amount / UNIT * price * .99:
            raise RuntimeError('Quote deviates by more than 1% from the observed pool price')
        minimum = quote * (10000-SLIPPAGE_BPS) // 10000
        deadline = int(time.time()) + 120
        if source == 'BNB':
            fn = self.chain.router.functions.swapExactETHForTokens(minimum, path, self.address, deadline)
        else:
            fn = self.chain.router.functions.swapExactTokensForTokens(amount, minimum, path, self.address, deadline)
        return self.submit(fn, kind, market, value=amount if source == 'BNB' else 0, reason=reason)
