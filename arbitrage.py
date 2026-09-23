"""Conservative, atomic PancakeSwap V2 triangle opportunities.

Every route starts and ends in the same owned token. Router quotes include all
three pool fees and price impact. A successful swap must return the original
token plus a gas budget and a small profit; failed swaps can still burn gas.
"""
import math

from market import TOKENS, UNIT

ROUTES = (
    ('USDT', 'BTCB', 'BNB', 'USDT'),
    ('USDT', 'BNB', 'BTCB', 'USDT'),
    ('BTCB', 'USDT', 'BNB', 'BTCB'),
    ('BTCB', 'BNB', 'USDT', 'BTCB'),
)
MAX_NOTIONAL_USD = 20.0
MIN_NOTIONAL_USD = 5.0
ARB_GAS_CAP_USD = .03  # Each of an approval and a swap must stay under this cap.
MIN_NET_GAIN_USD = .02
QUOTE_BUFFER_USD = .02
SCAN_SECONDS = 30
MAX_DAILY_ARBS = 24
ARB_COOLDOWN_SECONDS = 120


def scan(market, balances, quote):
    """Return the best route and an eligible candidate using exact integer quotes.

    quote(route, amount) must return the onchain router's final integer output.
    The trade threshold budgets two transactions even if approval already exists.
    """
    best, errors = None, 0
    for asset in ('USDT', 'BTCB'):
        price = 1.0 if asset == 'USDT' else market['BTCB']['price']
        amount = min(balances[asset], int(MAX_NOTIONAL_USD / price * UNIT))
        notional = amount / UNIT * price
        if notional < MIN_NOTIONAL_USD:
            continue
        for route in ROUTES:
            if route[0] != asset:
                continue
            try:
                output = int(quote(route, amount))
            except Exception:
                errors += 1
                continue
            gain = (output - amount) / UNIT * price
            if best is None or gain > best['gross_gain_usd']:
                floor = 2 * ARB_GAS_CAP_USD + MIN_NET_GAIN_USD
                best = {'route': route, 'asset': asset, 'amount': amount,
                        'quoted_out': output, 'notional_usd': notional,
                        'gross_gain_usd': gain,
                        'min_out': amount + math.ceil(floor / price * UNIT),
                        'required_gain_usd': floor + QUOTE_BUFFER_USD,
                        'asset_price': price}
    if best is None:
        return {'status': 'No funded route' if not errors else 'Router quotes unavailable',
                'best': None, 'candidate': None, 'errors': errors}
    candidate = best if best['gross_gain_usd'] >= best['required_gain_usd'] else None
    status = ('Qualified atomic triangle' if candidate else
              f"Best triangle {best['gross_gain_usd']:+.4f} USD before gas; "
              f"requires at least +${best['required_gain_usd']:.2f}")
    return {'status': status, 'best': best, 'candidate': candidate, 'errors': errors}


def chain_quote(chain, market, route, amount):
    if route not in ROUTES:
        raise ValueError('Unapproved arbitrage route')
    return chain.router.functions.getAmountsOut(
        amount, [TOKENS[symbol] for symbol in route]
    ).call(block_identifier=market['block'])[-1]
