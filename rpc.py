"""Bounded retries for public reads; broadcasts are never retried here."""
from web3 import HTTPProvider, Web3

READ_METHODS = {'eth_call', 'eth_chainId', 'eth_blockNumber', 'eth_getBlockByNumber',
                'eth_getBalance', 'eth_gasPrice', 'eth_getCode',
                'eth_getTransactionCount', 'eth_getTransactionReceipt'}


class ReadFailoverProvider(HTTPProvider):
    def __init__(self, urls):
        super().__init__(urls[0], request_kwargs={'timeout': 4}, exception_retry_configuration=None)
        self.providers = [HTTPProvider(u, request_kwargs={'timeout': 4},
                                      exception_retry_configuration=None) for u in urls]
        self.current = 0

    def make_request(self, method, params):
        attempts = min(2, len(self.providers)) if method in READ_METHODS else 1
        for offset in range(attempts):
            index = (self.current + offset) % len(self.providers)
            provider = self.providers[index]
            try:
                if offset:
                    identity = provider.make_request('eth_chainId', [])
                    if identity.get('result') != '0x38':
                        raise RuntimeError('Fallback endpoint is not BNB Chain')
                result = provider.make_request(method, params)
                error = result.get('error', {})
                message = str(error.get('message', '')).lower()
                transient = error.get('code') in (-32005, -32002) or any(
                    s in message for s in ('rate limit', 'timeout', 'header not found', 'missing trie'))
                if transient and offset + 1 < attempts:
                    continue
                self.current = index
                return result
            except Exception:
                if offset + 1 == attempts:
                    raise
        raise RuntimeError('RPC read failed')


MULTICALL = Web3.to_checksum_address('0xcA11bde05977b3631167028862bE2a173976CA11')
MULTICALL_ABI = [{
    'type': 'function', 'name': 'aggregate3', 'stateMutability': 'payable',
    'inputs': [{'name': 'calls', 'type': 'tuple[]', 'components': [
        {'name': 'target', 'type': 'address'}, {'name': 'allowFailure', 'type': 'bool'},
        {'name': 'callData', 'type': 'bytes'}]}],
    'outputs': [{'name': 'results', 'type': 'tuple[]', 'components': [
        {'name': 'success', 'type': 'bool'}, {'name': 'returnData', 'type': 'bytes'}]}]
}]


def batch_read(w3, functions, block='latest', gas=12_000_000):
    """One eth_call, one block, individually decoded successes. No transaction."""
    if not functions:
        return []
    contract = w3.eth.contract(address=MULTICALL, abi=MULTICALL_ABI)
    calls = [(f.address, True, f._encode_transaction_data()) for f in functions]
    raw = contract.functions.aggregate3(calls).call({'gas': gas}, block_identifier=block)
    if len(raw) != len(functions):
        raise RuntimeError('Incomplete batched RPC response')
    results = []
    for f, (success, data) in zip(functions, raw):
        try:
            decoded = w3.codec.decode([x['type'] for x in f.abi['outputs']], data) if success else None
        except Exception:
            decoded = None
        results.append(decoded)
    return results
