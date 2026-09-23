"""Conservative, atomic PancakeSwap V2 triangle opportunities.

Every route starts and ends in the same owned token. Router quotes include all
three pool fees and price impact. A successful swap must return the original
token plus a gas budget and a small profit; failed swaps can still burn gas.
"""
import math
import time

from market import TOKENS, UNIT

ROUTES = (
    ('USDT', 'BTCB', 'BNB', 'USDT'),
    ('USDT', 'BNB', 'BTCB', 'USDT'),
    ('BTCB', 'USDT', 'BNB', 'BTCB'),
    ('BTCB', 'BNB', 'USDT', 'BTCB'),
) + tuple(route for asset in ('ETH', 'USDC', 'CAKE') for route in (
    ('USDT', asset, 'BNB', 'USDT'), ('USDT', 'BNB', asset, 'USDT')))
MAX_NOTIONAL_USD = 20.0
MIN_NOTIONAL_USD = 5.0
ARB_GAS_CAP_USD = .03  # Each of an approval and a swap must stay under this cap.
MIN_NET_GAIN_USD = .02
QUOTE_BUFFER_USD = .02
SCAN_SECONDS = 10
MAX_DAILY_ARBS = 24
ARB_COOLDOWN_SECONDS = 120


def gas_budgets(market):
    """Enforced spending caps, using current gas and 50% estimation headroom.

    Always reserve approval cost even when allowance already exists. The executor
    refuses a transaction whose padded estimate exceeds its corresponding cap.
    """
    unit_cost = market['gas_price'] / UNIT * market['BNB']['price']
    return {'approval': min(ARB_GAS_CAP_USD, 80_000 * unit_cost * 1.5),
            'swap': min(ARB_GAS_CAP_USD, 300_000 * unit_cost * 1.5)}


def make_candidate(market, route, amount, output, approval_cost_usd=0):
    asset = route[0]
    price = 1.0 if asset == 'USDT' else market['BTCB']['price']
    budgets = gas_budgets(market)
    gain = (output-amount)/UNIT*price
    floor = sum(budgets.values()) + approval_cost_usd + MIN_NET_GAIN_USD
    return {'route': route, 'asset': asset, 'amount': amount, 'quoted_out': output,
            'notional_usd': amount/UNIT*price, 'gross_gain_usd': gain,
            'min_out': amount + math.ceil(floor/price*UNIT),
            'required_gain_usd': floor + QUOTE_BUFFER_USD, 'gas_budgets': budgets,
            'approval_cost_usd': approval_cost_usd, 'asset_price': price,
            'net_gain_usd': gain-sum(budgets.values())-approval_cost_usd,
            'venue': 'V2', 'pool_fee_pct': .75,
            'quoted_at': market['time'], 'block': market.get('block')}


def summarize(candidates, errors, checked, **extra):
    best = max(candidates, key=lambda c: c['net_gain_usd'], default=None)
    qualified = [c for c in candidates if c['gross_gain_usd'] >= c['required_gain_usd']]
    candidate = max(qualified, key=lambda c: c['net_gain_usd'], default=None)
    status = ('Qualified atomic round trip' if candidate else
              f"Best round trip {best['net_gain_usd']:+.4f} USD after gas budget; no qualifying edge" if best else
              'Router quotes unavailable' if errors else 'No funded route')
    return {'status': status, 'best': best, 'candidate': candidate, 'errors': errors,
            'quotes_checked': checked, **extra}


def quote_jobs(market, balances):
    for asset in ('USDT', 'BTCB'):
        price = 1.0 if asset == 'USDT' else market['BTCB']['price']
        maximum = min(balances[asset], int(MAX_NOTIONAL_USD / price * UNIT))
        if maximum / UNIT * price < MIN_NOTIONAL_USD:
            continue
        # A smaller order can have better net gain when price impact is material.
        amounts = sorted({maximum, min(maximum, int(10 / price * UNIT)),
                          min(maximum, math.ceil(MIN_NOTIONAL_USD / price * UNIT))})
        for route, amount in ((r, a) for r in ROUTES for a in amounts):
            if route[0] != asset:
                continue
            yield route, amount


def scan(market, balances, quote, approval_cost_usd=0):
    candidates, errors, checked = [], 0, 0
    for route, amount in quote_jobs(market, balances):
        checked += 1
        try:
            output = int(quote(route, amount))
        except Exception:
            errors += 1
            continue
        candidates.append(make_candidate(market, route, amount, output, approval_cost_usd))
    return summarize(candidates, errors, checked)


def scan_markets(chain, v3, market, balances, approval_cost_usd=0):
    """Batch all V2 quotes, then screen and quote distinct V3 pools."""
    jobs = list(quote_jobs(market, balances))
    candidates, errors, checked, venues = [], 0, 0, {}
    try:
        values = chain.batch([chain.router.functions.getAmountsOut(a, [TOKENS[s] for s in r])
                              for r, a in jobs], market['block'])
        for (route, amount), value in zip(jobs, values):
            checked += 1
            if value:
                candidates.append(make_candidate(market, route, amount, value[0][-1], approval_cost_usd))
            else:
                errors += 1
        venues['V2'] = {'quotes_checked': checked, 'errors': errors}
    except Exception:
        errors += len(jobs)
        venues['V2'] = {'error': 'Batch quotes unavailable'}
    try:
        result = v3.scan(market, balances, approval_cost_usd)
        venues['V3'] = {k: v for k, v in result.items() if k not in ('best', 'candidate')}
        candidates.extend(c for c in (result['best'], result['candidate']) if c)
        checked += result['quotes_checked']
        errors += result['errors']
    except Exception as exc:
        venues['V3'] = {'error': str(exc) if isinstance(exc, RuntimeError) else 'V3 market data unavailable'}
        errors += 1
    result = summarize(candidates, errors, checked, venues=venues, scanned_at=time.time())
    if time.time()-market['time'] > 30:
        result['candidate'] = None
        result['status'] = 'Scan expired; no execution from stale quotes'
    return result


def chain_quote(chain, market, route, amount):
    if route not in ROUTES:
        raise ValueError('Unapproved arbitrage route')
    if time.time() - market['time'] > 20:
        raise RuntimeError('Arbitrage scan time budget exhausted')
    return chain.router.functions.getAmountsOut(
        amount, [TOKENS[symbol] for symbol in route]
    ).call(block_identifier=market['block'])[-1]
