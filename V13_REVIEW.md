# v1.3 strategy and execution review

## Why activity and results were disappointing

The live ledger contained one $20 BTCB purchase followed by a 2% stop-triggered sale. These are two fills of one position. Its net loss was about $0.47 including the approvals and swap gas; initial funding costs and changes in the retained BNB gas reserve explain the remaining portfolio difference. No arbitrage cycle had executed. The running v1.2 process also reported expired snapshots and unavailable route quotes.

## Changes

The bot now evaluates USDT round trips through BNB, BTCB, ETH, USDC, and CAKE. V2 triangles are quoted in one batch. V3 uses two different pools for the same pair, with 0.01%, 0.05%, or 0.25% fees, instead of always paying three V2 pool fees. The router, factory, quoter, and token addresses come from PancakeSwap's published deployments and token list. Candidates start and end in the same owned token and use a single atomic router transaction with a minimum output above the starting amount and cost budget.

Required pool and balance reads are batched at one block. Public reads have a four-second timeout and at most one checked fallback endpoint. Transaction broadcasts have no automatic retries. V3 exact quote work is capped and all candidate timestamps are checked again before execution. Candle data refresh is independent, and cannot block arbitrage or protective exits. The dashboard reports completed positions separately from fills and approvals.

The $17 floor, stricter 5% account guard, exact allowances, $20 order cap, gas ceilings, 2% position stop, and persisted halt remain. New directional entries remain disabled by default. The requested $27 / five-hour goal is displayed; it does not weaken entry criteria or stops.

## Forward checks

Three consecutive read-only checks at BNB Chain blocks 123590773, 123590785, and 123590796 each completed 27 exact route/size quotes (24 V2, 3 V3) with zero errors. Total snapshot, balance, and scanner durations were 5.11, 5.11, and 5.13 seconds after initial contract verification. The V3 screening covered 10 eligible pools across five pairs and 12 directed fee-tier combinations. Screening omits routes whose no-impact bound is losing, except for the best diagnostic route; candidates always require an exact quoter result.

The best observed route was USDT → USDC → USDT using 0.01% and 0.05% pools. Its $5 quote lost approximately $0.00117 before gas and $0.02297 after the gas budget. It was rejected. These results demonstrate faster and wider market checks, not a profitable strategy record. They cannot establish that $27 will be reached in five hours. Raw observations are in V13_FORWARD_CHECK.json.

## Tests and deployment

55 tests pass locally. New tests cover V3 route/path encoding; distinct-pool enforcement; exact router approval and recipient; stale/unprofitable quote rejection before approval; output floors; locally signed V3 calldata; correct block use; V3 contract identity checks; one venue failing while another remains usable; RPC failover chain validation; no rebroadcast on timeout; candle independence; expired cached-candidate rejection; and completed-position accounting. The prior loss guards, receipt accounting, restart persistence, and replay prevention tests remain passing.

The full v1.3 paper worker and browser dashboard were checked on port 8768 using real public market data. It reports a healthy market connection, both venues, all five pairs, $27 target, $17 floor, and the existing effective account stop. No key was loaded and no live acceptance-test transaction was sent. V3 funded execution has not yet been validated on mainnet. Updating files does not reload the existing live process: follow RUN_LIVE.md to restart locally and retain the live ledger.

## Sources

- [PancakeSwap V3 deployments](https://developer.pancakeswap.finance/contracts/v3/addresses)
- [PancakeSwap V3 router interface](https://github.com/pancakeswap/pancake-v3-contracts/blob/main/projects/v3-periphery/contracts/interfaces/ISwapRouter.sol)
- [PancakeSwap V3 quoter source](https://github.com/pancakeswap/pancake-v3-contracts/blob/main/projects/v3-periphery/contracts/lens/QuoterV2.sol)
- [PancakeSwap token list](https://github.com/pancakeswap/token-list/blob/main/src/tokens/pancakeswap-extended.json)
- [Multicall3 deployment list](https://github.com/mds1/multicall3/blob/main/deployments.json)
- [BNB Chain RPC endpoints](https://docs.bnbchain.org/bnb-smart-chain/developers/json_rpc/json-rpc-endpoint/)
