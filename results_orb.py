import json, os, csv
from datetime import datetime
from shared.config import ORB_RUN_NAME

ORB_LOG_PATH      = "logs/backtest_log_ORB.json"
ORB_TRADE_CSV     = "logs/trade_log_ORB.csv"
ORB_FILTERED_CSV  = "logs/filtered_log_ORB.csv"



def save_orb_results(results):
    res = results["results"]

    eod_count = sum(1 for t in res["trade_log"] if t["result"] == "EOD_CLOSE")

    wins  = [t["r_multiple"] for t in res["trade_log"] if t["r_multiple"] > 0]
    losses = [t["r_multiple"] for t in res["trade_log"] if t["r_multiple"] < 0]

    avg_win_r  = round(sum(wins) / len(wins), 4) if wins else 0
    avg_loss_r = round(sum(losses) / len(losses), 4) if losses else 0
    ev = round((res["winrate"] * avg_win_r) + ((1 - res["winrate"]) * avg_loss_r), 4)

    eod_count = sum(1 for t in res["trade_log"] if t["result"] == "EOD_CLOSE")

    entry = {
        "date":          datetime.now().strftime("%Y-%m-%d %H:%M"),
        "run_name":      ORB_RUN_NAME,
        "final_equity":  round(res["final_equity"], 2),
        "trade_count":   res["trade_count"],
        "winning_trades": res["winning_trade_count"],
        "losing_trades": res["losing_trade_count"],
        "eod_closes":    eod_count,
        "avg_win_r":  avg_win_r,
        "avg_loss_r": avg_loss_r,
        "ev":         ev,
        "winrate":       round(res["winrate"], 4),
        "average_r":     round(res["average_r"], 4),
        "max_drawdown":  round(res["max_drawdown"], 4),
        "filter_counts": results["filter_counts"],
    }

    log = json.load(open(ORB_LOG_PATH)) if os.path.exists(ORB_LOG_PATH) else {}

    # Same name overwrites, new name adds
    log[ORB_RUN_NAME] = entry

    json.dump(log, open(ORB_LOG_PATH, "w"), indent=4)
    print(f"Backtest log  → {ORB_LOG_PATH}  [{ORB_RUN_NAME}]")


def save_orb_trade_log(results):
    log = results["results"]["trade_log"]
    if not log:
        print("No trades to save.")
        return
    with open(ORB_TRADE_CSV, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=log[0].keys())
        w.writeheader()
        w.writerows(log)
    print(f"Trade log     → {ORB_TRADE_CSV}  ({len(log)} trades)")


def save_filtered_log(results):
    log = results["filtered_log"]
    if not log:
        print("No filtered sessions.")
        return
    with open(ORB_FILTERED_CSV, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=log[0].keys())
        w.writeheader()
        w.writerows(log)
    print(f"Filtered log  → {ORB_FILTERED_CSV}  ({len(log)} sessions)")