# ORB Backtest Audit

An Opening Range Breakout (ORB) backtesting engine for equities — and the story of finding a look-ahead bias bug that made the strategy look far better than it actually is.

This repo isn't really about whether ORB is profitable. It's a case study in validating backtests before risking capital.

---

## The Strategy

A classic Opening Range Breakout:

1. Mark the high/low of the first 15-minute bar after market open (9:30 AM ET)
2. Wait for a confirmation close above the range high (long) or below the range low (short)
3. Enter via limit order at the range midpoint, or market order on confirmation (configurable)
4. Stop at the opposite side of the range, target at a fixed reward:risk ratio
5. Optional filters: ATR-based range sizing, directional bias, gap fade, ADX regime detection

The engine supports both **train** and **test** splits, full Monte Carlo simulation, and drawdown event analysis.

---

## The Bug

While auditing the engine for look-ahead bias, I found a flaw in the **limit entry path** — the default and primary mode this strategy uses.

### What was happening

When a limit order fills, the code needs to scan forward bar-by-bar to manage the trade (check for stop or target). The original code started that scan **on the same bar the limit order filled**:

```python
trade_bars = session_df.iloc[entry_bar_idx:]   # includes the fill bar itself
```

The problem: OHLC bar data has no information about the *order* of price movement within a bar. If the limit fill bar's high also happened to reach the target price, the code would record an instant win — assuming the fill happened first and the run to target happened after, within the same 15-minute bar.

But that ordering is unknowable from the data. It's equally possible price ran to target *before* ever touching the limit price — in which case the limit never fills, and there's no trade at all. The original code always picked the favorable interpretation.

### The fix

Trade management now starts on the bar **after** the fill bar — the only causally safe assumption:

```python
management_start_idx = entry_bar_idx + 1
...
trade_bars = session_df.iloc[management_start_idx:]   # line 369, engine_orb.py
```

(Edge case handled separately: if the fill happens on the session's last bar, the trade exits at that bar's close rather than looking for bars that don't exist.)

---

## The Impact

Same data, same strategy rules, same train period — only this one assumption changed.

| Metric | Before fix | After fix |
|---|---|---|
| Win rate | 51.4% | 40.1% |
| Avg win (R) | 1.49 | 1.49 |
| EV per trade | **+0.283R** | **+0.001R** |
| Max drawdown | -15.4% | -28.6% |
| Final equity ($10k start, ~4yr) | $43,575 | $9,417 |

The "edge" wasn't real. It was 11 percentage points of win rate manufactured by a single optimistic line of code — same-bar fills that resolved to instant wins more often than they reasonably should.

This matches a pattern worth internalizing: **any time a backtest lets one bar both establish entry and resolve the trade, check whether that's actually possible to know in real time.** If it isn't, the backtest is quietly cheating.

---

## Why This Matters

It's easy to build a backtest that looks great. It's much harder to build one you can actually trust enough to trade. The gap between "looks profitable on paper" and "is profitable" is usually hiding in exactly this kind of subtle, easy-to-miss assumption — not in the strategy logic itself.

This audit is part of a broader practice I apply to every strategy I build: explicit checks for look-ahead bias, inverted stop/target logic, and overfitting before any of it gets near real capital.

---

## Repo Structure

```
engine_orb.py       — core backtest loop, trade simulation, equity tracking
strategy_orb.py      — opening range detection, breakout confirmation, entry setup logic
main_orb.py           — entry point, train/test split, results printing, charts
results_orb.py        — trade log / backtest log persistence
config_example.py     — example configuration (rename to config.py, adjust paths/values)
```

To run:
```bash
python -m main_orb
```
(Requires your own historical OHLCV data — see `ORB_DATA_FILE` in config.)

---

## Equity Curves

*(Add screenshots here — before-fix and after-fix equity curves, side by side)*

---

## Tech

Python · pandas · matplotlib · Monte Carlo simulation · event-based drawdown analysis
