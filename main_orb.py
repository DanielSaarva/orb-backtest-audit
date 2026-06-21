import matplotlib.pyplot as plt
import pandas as pd
from .engine_orb import load_orb_data, run_orb_backtest
from .results_orb import save_orb_results, save_orb_trade_log, save_filtered_log
from shared.montecarlo import run_monte_carlo
from shared.config import (
    ORB_DATA_FILE, ORB_RISK_PER_TRADE, ORB_REWARD_RISK,
    ORB_MODE, ORB_TRAIN_YEARS, ORB_RUN_NAME,
)


# ---------------------------------------------------------------------------
# Drawdown analysis
# ---------------------------------------------------------------------------

def compute_drawdown_analysis(drawdown_curve):
    """
    Takes the drawdown curve (list of floats, each is equity/peak - 1)
    and returns event-based drawdown statistics.

    An "event" is a distinct drawdown episode — from the moment equity
    drops below its previous peak until it recovers back to a new peak.
    """
    # Average of all underwater points
    underwater   = [d for d in drawdown_curve if d < 0]
    avg_drawdown = sum(underwater) / len(underwater) if underwater else 0.0
    max_drawdown = min(drawdown_curve) if drawdown_curve else 0.0

    # Event-based tracking
    in_drawdown         = False
    current_event_min   = 0.0
    current_event_start = 0
    event_depths        = []
    event_durations     = []

    for i, d in enumerate(drawdown_curve):
        if d < 0:
            if not in_drawdown:
                # Start of a new drawdown episode
                in_drawdown         = True
                current_event_min   = d
                current_event_start = i
            else:
                # Deepen the current episode if we go lower
                if d < current_event_min:
                    current_event_min = d
        else:
            if in_drawdown:
                # Episode ended - equity recovered to new peak
                event_depths.append(current_event_min)
                event_durations.append(i - current_event_start)
                in_drawdown       = False
                current_event_min = 0.0

    # Close any episode still open at the end of the curve
    if in_drawdown:
        event_depths.append(current_event_min)
        event_durations.append(len(drawdown_curve) - current_event_start)

    event_count        = len(event_depths)
    avg_event_depth    = sum(event_depths)    / event_count if event_count > 0 else 0.0
    worst_event        = min(event_depths)                  if event_count > 0 else 0.0
    avg_event_duration = sum(event_durations) / event_count if event_count > 0 else 0.0
    max_event_duration = max(event_durations)               if event_count > 0 else 0

    return {
        "max_drawdown":        max_drawdown,
        "avg_drawdown":        avg_drawdown,
        "event_count":         event_count,
        "avg_event_depth":     avg_event_depth,
        "worst_event":         worst_event,
        "avg_event_duration":  avg_event_duration,
        "max_event_duration":  max_event_duration,
    }


# ---------------------------------------------------------------------------
# Load and split data
# ---------------------------------------------------------------------------

df = load_orb_data(ORB_DATA_FILE)

min_date   = df["timestamp_et"].dt.date.min()
split_date = (pd.Timestamp(min_date) + pd.DateOffset(years=ORB_TRAIN_YEARS)).date()

if ORB_MODE == "train":
    df         = df[df["timestamp_et"].dt.date < split_date].reset_index(drop=True)
    date_range = f"{min_date}  ->  {split_date}"
elif ORB_MODE == "test":
    df         = df[df["timestamp_et"].dt.date >= split_date].reset_index(drop=True)
    date_range = f"{split_date}  ->  {df['timestamp_et'].dt.date.max()}"
else:
    raise ValueError(f"ORB_MODE must be 'train' or 'test', got: {ORB_MODE!r}")

print(f"\nMode: {ORB_MODE.upper()}   |   {date_range}   |   {len(df)} bars")


# ---------------------------------------------------------------------------
# Run backtest
# ---------------------------------------------------------------------------

results = run_orb_backtest(df, risk_per_trade=ORB_RISK_PER_TRADE, reward_risk=ORB_REWARD_RISK)
res     = results["results"]
fc      = results["filter_counts"]

wins     = [t["r_multiple"] for t in res["trade_log"] if t["r_multiple"] > 0]
losses   = [t["r_multiple"] for t in res["trade_log"] if t["r_multiple"] < 0]
eod      = sum(1 for t in res["trade_log"] if t["result"] == "EOD_CLOSE")
avg_win  = sum(wins)   / len(wins)   if wins   else 0
avg_loss = sum(losses) / len(losses) if losses else 0
ev       = (res["winrate"] * avg_win) + ((1 - res["winrate"]) * avg_loss)


# ---------------------------------------------------------------------------
# Print results
# ---------------------------------------------------------------------------

print(f"\n{'─'*40}")
print(f"  ORB  —  {ORB_RUN_NAME}")
print(f"{'─'*40}")
print(f"  Final equity:     ${res['final_equity']:.2f}")
print(f"  Total trades:     {res['trade_count']}")
print(f"  Winning:          {res['winning_trade_count']}")
print(f"  Losing:           {res['losing_trade_count']}")
print(f"  EOD closes:       {eod}")
print(f"  Win rate:         {res['winrate']:.2%}")
print(f"  Avg win R:        {avg_win:.4f}")
print(f"  Avg loss R:       {avg_loss:.4f}")
print(f"  EV per trade:     {ev:.4f}R")
print(f"  Avg R:            {res['average_r']:.4f}")
print(f"  Max drawdown:     {res['max_drawdown']:.2%}")
print(f"{'─'*40}")
print(f"  Filtered sessions: {sum(fc.values())}")
print(f"    Bias neutral:    {fc['bias_neutral']}")
print(f"    Bias mismatch:   {fc['bias_direction_mismatch']}")
print(f"    ATR too large:   {fc['atr_too_large']}")
print(f"    ATR too small:   {fc['atr_too_small']}")
print(f"    Time expired:    {fc['time_expired']}")
print(f"    No OR bar:       {fc['no_or_bar']}")
print(f"    No entry bar:    {fc['no_entry_bar']}")
print(f"    Limit not filled: {fc['limit_not_filled']}")
print(f"    Gap neutral:     {fc['gap_neutral']}")
print(f"    Gap mismatch:    {fc['gap_direction_mismatch']}")
print(f"    ADX transitioning: {fc['adx_transitioning']}")
print(f"    ADX dir mismatch:  {fc['adx_direction_mismatch']}")
print(f"{'─'*40}")

# Drawdown analysis
dd = compute_drawdown_analysis(res["drawdowns"])

print(f"  Drawdown Analysis")
print(f"{'─'*40}")
print(f"  Max drawdown:          {dd['max_drawdown']:.2%}")
print(f"  Avg drawdown:          {dd['avg_drawdown']:.2%}")
print(f"  Drawdown events:       {dd['event_count']}")
print(f"  Avg drawdown/event:    {dd['avg_event_depth']:.2%}")
print(f"  Worst event:           {dd['worst_event']:.2%}")
print(f"  Avg event duration:    {dd['avg_event_duration']:.1f} trades")
print(f"  Max event duration:    {dd['max_event_duration']} trades")
print(f"{'─'*40}")

if results["logs"]:
    print("\n--- Engine Warnings ---")
    for entry in results["logs"]:
        print(f"  {entry}")


# ---------------------------------------------------------------------------
# Save logs
# ---------------------------------------------------------------------------

save_orb_results(results)
save_orb_trade_log(results)
save_filtered_log(results)


# ---------------------------------------------------------------------------
# Charts
# ---------------------------------------------------------------------------

plt.figure()
plt.plot(res["equity_curve"])
plt.title(f"ORB Equity Curve — {ORB_MODE.upper()}")
plt.xlabel("Trade #")
plt.ylabel("Equity ($)")
plt.tight_layout()

plt.figure()
plt.plot(res["drawdowns"])
plt.title(f"ORB Drawdown — {ORB_MODE.upper()}")
plt.xlabel("Trade #")
plt.ylabel("Drawdown")
plt.tight_layout()

run_monte_carlo(results)
plt.show()