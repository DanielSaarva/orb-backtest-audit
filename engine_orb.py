import pandas as pd
from shared.config import (
    ORB_ATR_PERIOD,
    ORB_USE_BIAS_FILTER, ORB_ENTRY_TYPE,
    ORB_USE_GAP_FILTER, ORB_GAP_LONG_THRESHOLD, ORB_GAP_SHORT_THRESHOLD,
    ORB_USE_ADX_FILTER, ORB_ADX_MARKET_RISK,
    ORB_TIME_CUTOFF_HOUR, ORB_TIME_CUTOFF_MINUTE,
    ORB_SLIPPAGE, ORB_COMMISSION,
)
from .strategy_orb import compute_atr, get_sessions, analyze_session
from bias.nq_bias.calculate_bias_history import load_bias_history
from shared.adx import load_adx_history


def load_orb_data(filepath):
    df = pd.read_csv(filepath)
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    df["timestamp_et"] = df["timestamp"].dt.tz_convert("America/New_York")
    df = df.sort_values("timestamp_et").reset_index(drop=True)

    market_open  = (df["timestamp_et"].dt.hour > 9) | (
                   (df["timestamp_et"].dt.hour == 9) & (df["timestamp_et"].dt.minute >= 30))
    market_close =  df["timestamp_et"].dt.hour < 16
    df = df[market_open & market_close].reset_index(drop=True)
    return df


def build_prev_close_map(df):
    df = df.copy()
    df["session_date"] = df["timestamp_et"].dt.date
    daily_last_close = (
        df.groupby("session_date")["close"]
        .last()
        .reset_index()
        .rename(columns={"close": "last_close"})
    )
    daily_last_close = daily_last_close.sort_values("session_date").reset_index(drop=True)
    prev_close_map = {}
    for i in range(1, len(daily_last_close)):
        current_date = daily_last_close.iloc[i]["session_date"]
        prev_close   = daily_last_close.iloc[i - 1]["last_close"]
        prev_close_map[str(current_date)] = prev_close
    return prev_close_map


def run_orb_backtest(df, risk_per_trade, reward_risk):
    atr_series = compute_atr(df, period=ORB_ATR_PERIOD)
    df = df.copy()
    df["atr"] = atr_series

    sessions       = get_sessions(df)
    bias_history   = load_bias_history() if ORB_USE_BIAS_FILTER else {}
    prev_close_map = build_prev_close_map(df) if ORB_USE_GAP_FILTER else {}
    adx_history    = load_adx_history() if ORB_USE_ADX_FILTER else {}

    equity       = 10000.0
    peak         = equity
    max_drawdown = 0.0

    trade_count         = 0
    winning_trade_count = 0
    losing_trade_count  = 0

    trade_returns     = []
    trade_r_multiples = []
    equity_curve      = [equity]
    drawdown_curve    = [0.0]
    trade_log         = []
    filtered_log      = []
    logs              = []

    filter_counts = {
        "atr_too_large":           0,
        "atr_too_small":           0,
        "time_expired":            0,
        "no_or_bar":               0,
        "no_entry_bar":            0,
        "bias_neutral":            0,
        "bias_direction_mismatch": 0,
        "limit_not_filled":        0,
        "gap_neutral":             0,
        "gap_direction_mismatch":  0,
        "adx_transitioning":       0,
        "adx_direction_mismatch":  0,
        "no_bars_after_fill":      0,
    }

    for date in sorted(sessions.keys()):
        session_df       = sessions[date]
        session_date_str = str(date)

        # ------------------------------------------------------------------
        # NQ Bias filter
        # ------------------------------------------------------------------
        if ORB_USE_BIAS_FILTER:
            bias_direction = bias_history.get(session_date_str, "neutral")
            if bias_direction == "neutral":
                filter_counts["bias_neutral"] += 1
                filtered_log.append({
                    "date": session_date_str, "or_high": None, "or_low": None,
                    "or_size": None, "atr": None, "or_size_vs_atr": None,
                    "filter_reason": "bias_neutral",
                })
                continue
        else:
            bias_direction = "both"

        # ------------------------------------------------------------------
        # Gap filter
        # ------------------------------------------------------------------
        if ORB_USE_GAP_FILTER:
            prev_close = prev_close_map.get(session_date_str)
            if prev_close is None:
                filter_counts["gap_neutral"] += 1
                filtered_log.append({
                    "date": session_date_str, "or_high": None, "or_low": None,
                    "or_size": None, "atr": None, "or_size_vs_atr": None,
                    "filter_reason": "gap_neutral",
                })
                continue

            or_mask = (
                (session_df["timestamp_et"].dt.hour == 9) &
                (session_df["timestamp_et"].dt.minute == 30)
            )
            or_bars = session_df[or_mask]
            if or_bars.empty:
                filter_counts["gap_neutral"] += 1
                filtered_log.append({
                    "date": session_date_str, "or_high": None, "or_low": None,
                    "or_size": None, "atr": None, "or_size_vs_atr": None,
                    "filter_reason": "gap_neutral",
                })
                continue

            open_price = or_bars.iloc[0]["open"]
            gap_pct    = (open_price - prev_close) / prev_close * 100

            if gap_pct >= ORB_GAP_LONG_THRESHOLD:
                gap_direction = "short"   # fade the gap
            elif gap_pct <= -ORB_GAP_SHORT_THRESHOLD:
                gap_direction = "long"    # fade the gap
            else:
                filter_counts["gap_neutral"] += 1
                filtered_log.append({
                    "date": session_date_str, "or_high": None, "or_low": None,
                    "or_size": None, "atr": None, "or_size_vs_atr": None,
                    "filter_reason": "gap_neutral",
                })
                continue
        else:
            gap_direction = "both"

        # ------------------------------------------------------------------
        # ADX data for this session
        # ------------------------------------------------------------------
        adx_data = adx_history.get(session_date_str) if ORB_USE_ADX_FILTER else None

        # ------------------------------------------------------------------
        # Pull ATR at OR bar
        # ------------------------------------------------------------------
        or_mask = (
            (session_df["timestamp_et"].dt.hour == 9) &
            (session_df["timestamp_et"].dt.minute == 30)
        )
        or_bars_atr = session_df[or_mask]
        if or_bars_atr.empty:
            atr_value = None
        else:
            or_time    = or_bars_atr.iloc[0]["timestamp_et"]
            global_row = df[df["timestamp_et"] == or_time]
            atr_value  = global_row.iloc[0]["atr"] if not global_row.empty else None

        setup = analyze_session(session_df, atr_value, adx_data=adx_data)

        # ------------------------------------------------------------------
        # Handle filter reasons
        # ------------------------------------------------------------------
        if not setup["trade_taken"]:
            reason = setup["filter_reason"] or "unknown"
            if reason in filter_counts:
                filter_counts[reason] += 1
            filtered_log.append({
                "date":          session_date_str,
                "or_high":       round(setup["or_high"], 4) if setup["or_high"] else None,
                "or_low":        round(setup["or_low"],  4) if setup["or_low"]  else None,
                "or_size":       round(setup["or_size"], 4) if setup["or_size"] else None,
                "atr":           round(float(atr_value), 4) if atr_value is not None and not pd.isna(atr_value) else None,
                "or_size_vs_atr": (
                    round(setup["or_size"] / float(atr_value), 3)
                    if setup["or_size"] and atr_value is not None
                    and not pd.isna(atr_value) and float(atr_value) > 0
                    else None
                ),
                "adx": adx_data["adx"] if adx_data else None,
                "filter_reason": reason,
            })
            continue

        # ------------------------------------------------------------------
        # Direction mismatch checks
        # ------------------------------------------------------------------
        if ORB_USE_BIAS_FILTER and bias_direction != "both" and setup["direction"] != bias_direction:
            filter_counts["bias_direction_mismatch"] += 1
            filtered_log.append({
                "date": session_date_str,
                "or_high": round(setup["or_high"], 4), "or_low": round(setup["or_low"], 4),
                "or_size": round(setup["or_size"], 4),
                "atr": round(float(atr_value), 4) if atr_value is not None and not pd.isna(atr_value) else None,
                "or_size_vs_atr": None, "adx": adx_data["adx"] if adx_data else None,
                "filter_reason": "bias_direction_mismatch",
            })
            continue

        if ORB_USE_GAP_FILTER and gap_direction != "both" and setup["direction"] != gap_direction:
            filter_counts["gap_direction_mismatch"] += 1
            filtered_log.append({
                "date": session_date_str,
                "or_high": round(setup["or_high"], 4), "or_low": round(setup["or_low"], 4),
                "or_size": round(setup["or_size"], 4),
                "atr": round(float(atr_value), 4) if atr_value is not None and not pd.isna(atr_value) else None,
                "or_size_vs_atr": None, "adx": adx_data["adx"] if adx_data else None,
                "filter_reason": "gap_direction_mismatch",
            })
            continue

        direction    = setup["direction"]
        entry_mode   = setup["entry_mode"]

        # ------------------------------------------------------------------
        # LIMIT ENTRY path
        # ------------------------------------------------------------------
        if setup["limit_pending"]:
            limit_price      = setup["entry_price"]
            confirmation_idx = setup["confirmation_bar_idx"]
            post_confirm     = session_df.iloc[confirmation_idx + 1:]

            # FIX: use configured cutoff instead of hardcoded 11:30
            cutoff_mask = (
                (post_confirm["timestamp_et"].dt.hour < ORB_TIME_CUTOFF_HOUR) |
                (
                    (post_confirm["timestamp_et"].dt.hour == ORB_TIME_CUTOFF_HOUR) &
                    (post_confirm["timestamp_et"].dt.minute <= ORB_TIME_CUTOFF_MINUTE)
                )
            )
            scannable  = post_confirm[cutoff_mask]
            fill_found = False

            for scan_idx in scannable.index:
                bar = session_df.iloc[scan_idx]
                if direction == "long" and bar["low"] <= limit_price:
                    fill_found    = True
                    entry_bar_idx = scan_idx
                    break
                elif direction == "short" and bar["high"] >= limit_price:
                    fill_found    = True
                    entry_bar_idx = scan_idx
                    break

            if not fill_found:
                filter_counts["limit_not_filled"] += 1
                filtered_log.append({
                    "date":          session_date_str,
                    "or_high":       round(setup["or_high"], 4),
                    "or_low":        round(setup["or_low"],  4),
                    "or_size":       round(setup["or_size"], 4),
                    "atr":           round(float(atr_value), 4) if atr_value is not None and not pd.isna(atr_value) else None,
                    "or_size_vs_atr": (
                        round(setup["or_size"] / float(atr_value), 3)
                        if setup["or_size"] and atr_value is not None
                        and not pd.isna(atr_value) and float(atr_value) > 0
                        else None
                    ),
                    "adx": adx_data["adx"] if adx_data else None,
                    "filter_reason": "limit_not_filled",
                })
                continue

            entry_price = limit_price
            stop_price  = setup["stop_price"]

            if direction == "long":
                risk_per_unit = entry_price - stop_price
                target_price  = entry_price + reward_risk * risk_per_unit
            else:
                risk_per_unit = stop_price - entry_price
                target_price  = entry_price - reward_risk * risk_per_unit

            if risk_per_unit <= 0:
                logs.append(f"{date}: limit fill skipped — risk_per_unit <= 0")
                continue

            # ------------------------------------------------------------
            # FIX (look-ahead): management starts on the bar AFTER the
            # fill bar, not the fill bar itself.
            #
            # The fill bar was selected because price touched the limit
            # level intrabar. Checking that SAME bar's high/low for
            # target/stop assumes a specific (unknowable) order of events
            # within the bar — and was previously letting trades record
            # an instant +reward_risk win if the retracement bar that
            # filled the limit also happened to have a high reaching the
            # target. This is optimistic and not reliably realisable live.
            #
            # If the fill happens on the session's last bar, there are no
            # bars left to manage — exit at that bar's close (EOD).
            # ------------------------------------------------------------
            management_start_idx = entry_bar_idx + 1
            if management_start_idx >= len(session_df):
                fill_bar    = session_df.iloc[entry_bar_idx]
                exit_price  = fill_bar["close"]
                if direction == "long":
                    trade_result_r = (exit_price - entry_price) / risk_per_unit
                else:
                    trade_result_r = (entry_price - exit_price) / risk_per_unit

                risk_amount     = equity * (ORB_ADX_MARKET_RISK if entry_mode == "market" else risk_per_trade)
                commission_cost = risk_amount * ORB_COMMISSION
                pnl             = (trade_result_r * risk_amount) - commission_cost
                result_label    = "EOD_CLOSE"

                if pnl >= 0:
                    winning_trade_count += 1
                else:
                    losing_trade_count += 1

                equity_before = equity
                equity       += pnl
                trade_count  += 1
                trade_returns.append(pnl / equity_before)
                trade_r_multiples.append(trade_result_r)
                equity_curve.append(equity)

                if equity > peak:
                    peak = equity
                drawdown = (equity / peak) - 1
                drawdown_curve.append(drawdown)
                if drawdown < max_drawdown:
                    max_drawdown = drawdown

                trade_log.append({
                    "date":          session_date_str,
                    "direction":     direction,
                    "entry_type":    entry_mode,
                    "bias":          bias_direction,
                    "gap_direction": gap_direction if ORB_USE_GAP_FILTER else "off",
                    "adx":           round(adx_data["adx"], 2) if adx_data else None,
                    "entry_mode":    entry_mode,
                    "or_high":       round(setup["or_high"], 4),
                    "or_low":        round(setup["or_low"],  4),
                    "or_midpoint":   round(setup["or_midpoint"], 4),
                    "or_size":       round(setup["or_size"], 4),
                    "atr":           round(float(atr_value), 4) if atr_value is not None and not pd.isna(atr_value) else None,
                    "or_size_vs_atr": (
                        round(setup["or_size"] / float(atr_value), 3)
                        if atr_value is not None and not pd.isna(atr_value) and float(atr_value) > 0
                        else None
                    ),
                    "entry_price":   round(entry_price,   4),
                    "stop_price":    round(stop_price,     4),
                    "target_price":  round(target_price,   4),
                    "exit_price":    round(exit_price,     4),
                    "result":        result_label,
                    "r_multiple":    round(trade_result_r, 4),
                    "pnl":           round(pnl, 2),
                })
                continue   # next session

            trade_bars = session_df.iloc[management_start_idx:]

        # ------------------------------------------------------------------
        # MARKET ENTRY path
        # ------------------------------------------------------------------
        else:
            entry_price_raw = setup["entry_price"]
            stop_price      = setup["stop_price"]
            entry_bar_idx   = setup["entry_bar_idx"]

            if direction == "long":
                entry_price   = entry_price_raw * (1 + ORB_SLIPPAGE)
                risk_per_unit = entry_price - stop_price
                target_price  = entry_price + reward_risk * risk_per_unit
            else:
                entry_price   = entry_price_raw * (1 - ORB_SLIPPAGE)
                risk_per_unit = stop_price - entry_price
                target_price  = entry_price - reward_risk * risk_per_unit

            if risk_per_unit <= 0:
                logs.append(f"{date}: skipped — risk_per_unit <= 0 after slippage")
                continue

            # Market entry: entered at this bar's OPEN, so checking this
            # same bar's high/low for stop/target is causal (no look-ahead).
            trade_bars = session_df.iloc[entry_bar_idx:]

        risk_amount = equity * (ORB_ADX_MARKET_RISK if entry_mode == "market" else risk_per_trade)
        commission_cost = risk_amount * ORB_COMMISSION

        # ------------------------------------------------------------------
        # Manage trade bar by bar
        # ------------------------------------------------------------------
        result_label   = "EOD_CLOSE"
        exit_price     = None
        trade_result_r = 0.0
        pnl            = 0.0

        for local_idx in range(len(trade_bars)):
            bar = trade_bars.iloc[local_idx]

            if direction == "long":
                stop_hit   = bar["low"]  <= stop_price
                target_hit = bar["high"] >= target_price
            else:
                stop_hit   = bar["high"] >= stop_price
                target_hit = bar["low"]  <= target_price

            if stop_hit and target_hit:
                result_label   = "STOP_AND_TARGET_SAME_BAR"
                exit_price     = stop_price
                trade_result_r = -1.0
                pnl            = -risk_amount - commission_cost
                losing_trade_count += 1
                break
            elif stop_hit:
                result_label   = "STOP"
                exit_price     = stop_price
                trade_result_r = -1.0
                pnl            = -risk_amount - commission_cost
                losing_trade_count += 1
                break
            elif target_hit:
                result_label   = "TARGET"
                exit_price     = target_price
                trade_result_r = reward_risk
                pnl            = (risk_amount * reward_risk) - commission_cost
                winning_trade_count += 1
                break

        if result_label == "EOD_CLOSE":
            last_bar   = trade_bars.iloc[-1]
            exit_price = last_bar["close"]
            if direction == "long":
                trade_result_r = (exit_price - entry_price) / risk_per_unit
            else:
                trade_result_r = (entry_price - exit_price) / risk_per_unit
            pnl = (trade_result_r * risk_amount) - commission_cost
            if pnl >= 0:
                winning_trade_count += 1
            else:
                losing_trade_count += 1

        # ------------------------------------------------------------------
        # Update equity
        # ------------------------------------------------------------------
        equity_before = equity
        equity       += pnl
        trade_count  += 1
        trade_returns.append(pnl / equity_before)
        trade_r_multiples.append(trade_result_r)
        equity_curve.append(equity)

        if equity > peak:
            peak = equity
        drawdown = (equity / peak) - 1
        drawdown_curve.append(drawdown)
        if drawdown < max_drawdown:
            max_drawdown = drawdown

        trade_log.append({
            "date":          session_date_str,
            "direction":     direction,
            "entry_type":    entry_mode,
            "bias":          bias_direction,
            "gap_direction": gap_direction if ORB_USE_GAP_FILTER else "off",
            "adx":           round(adx_data["adx"], 2) if adx_data else None,
            "entry_mode":    entry_mode,
            "or_high":       round(setup["or_high"], 4),
            "or_low":        round(setup["or_low"],  4),
            "or_midpoint":   round(setup["or_midpoint"], 4),
            "or_size":       round(setup["or_size"], 4),
            "atr":           round(float(atr_value), 4) if atr_value is not None and not pd.isna(atr_value) else None,
            "or_size_vs_atr": (
                round(setup["or_size"] / float(atr_value), 3)
                if atr_value is not None and not pd.isna(atr_value) and float(atr_value) > 0
                else None
            ),
            "entry_price":   round(entry_price,   4),
            "stop_price":    round(stop_price,     4),
            "target_price":  round(target_price,   4),
            "exit_price":    round(exit_price,     4),
            "result":        result_label,
            "r_multiple":    round(trade_result_r, 4),
            "pnl":           round(pnl, 2),
        })

    if trade_count > 0:
        winrate       = winning_trade_count / trade_count
        average_trade = sum(trade_returns) / len(trade_returns)
        average_r     = sum(trade_r_multiples) / len(trade_r_multiples)
    else:
        winrate = average_trade = average_r = 0.0

    return {
        "results": {
            "final_equity":        equity,
            "equity_curve":        equity_curve,
            "drawdowns":           drawdown_curve,
            "max_drawdown":        max_drawdown,
            "trade_count":         trade_count,
            "winning_trade_count": winning_trade_count,
            "losing_trade_count":  losing_trade_count,
            "winrate":             winrate,
            "average_trade":       average_trade,
            "average_r":           average_r,
            "trade_returns":       trade_returns,
            "trade_r_multiples":   trade_r_multiples,
            "trade_log":           trade_log,
        },
        "filtered_log":  filtered_log,
        "filter_counts": filter_counts,
        "logs":          logs,
    }