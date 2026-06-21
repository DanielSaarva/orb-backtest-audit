import pandas as pd
from shared.config import (
    ORB_ATR_PERIOD, ORB_ATR_MAX_MULT, ORB_ATR_MIN_MULT,
    ORB_REWARD_RISK, ORB_TIME_CUTOFF_HOUR, ORB_TIME_CUTOFF_MINUTE,
    ORB_ENTRY_TYPE, ORB_USE_ADX_FILTER,
    ORB_ADX_LOW_THRESHOLD, ORB_ADX_HIGH_THRESHOLD, ORB_ADX_MARKET_STOP_PCT, ORB_USE_ATR_FILTER
)


def compute_atr(df, period=ORB_ATR_PERIOD):
    high       = df["high"]
    low        = df["low"]
    prev_close = df["close"].shift(1)
    tr = pd.concat([
        (high - low),
        (high - prev_close).abs(),
        (low  - prev_close).abs(),
    ], axis=1).max(axis=1)
    return tr.rolling(window=period).mean()


def get_sessions(df):
    df = df.copy()
    df["session_date"] = df["timestamp_et"].dt.date
    sessions = {}
    for date, group in df.groupby("session_date"):
        sessions[date] = group.reset_index(drop=True)
    return sessions


def analyze_session(session_df, atr_value, adx_data=None):
    # ---------------------------------------------------------------------------
    # adx_data: dict with keys "adx", "plus_di", "minus_di" for this session date
    #           or None if ADX filter is disabled
    #
    # Entry mode logic:
    #   ADX filter off          → use ORB_ENTRY_TYPE from config (limit or market)
    #   ADX filter on:
    #     adx < ADX_LOW         → limit entry at midpoint
    #     adx > ADX_HIGH        → market entry with 25% OR stop
    #     ADX_LOW <= adx <= ADX_HIGH → skip session (adx_transitioning)
    # ---------------------------------------------------------------------------

    result = {
        "or_high":              None,
        "or_low":               None,
        "or_size":              None,
        "or_midpoint":          None,
        "filter_reason":        None,
        "trade_taken":          False,
        "limit_pending":        False,
        "direction":            None,
        "confirmation_bar_idx": None,
        "entry_bar_idx":        None,
        "entry_price":          None,
        "stop_price":           None,
        "target_price":         None,
        "entry_mode":           None,   # "limit" or "market" — which mode was used
    }

    # --- Determine entry mode for this session ---
    if ORB_USE_ADX_FILTER and adx_data is not None:
        adx_val = adx_data["adx"]

        if adx_val < ORB_ADX_LOW_THRESHOLD:
            session_entry_type = "limit"
        elif adx_val > ORB_ADX_HIGH_THRESHOLD:
            session_entry_type = "market"
        else:
            result["filter_reason"] = "adx_transitioning"
            return result
    else:
        session_entry_type = ORB_ENTRY_TYPE

    # --- Find the 9:30 ET opening range bar ---
    or_mask = (
        (session_df["timestamp_et"].dt.hour == 9) &
        (session_df["timestamp_et"].dt.minute == 30)
    )
    or_bars = session_df[or_mask]

    if or_bars.empty:
        result["filter_reason"] = "no_or_bar"
        return result

    or_idx      = or_bars.index[0]
    or_bar      = session_df.iloc[or_idx]
    or_high     = or_bar["high"]
    or_low      = or_bar["low"]
    or_size     = or_high - or_low
    or_midpoint = (or_high + or_low) / 2

    result["or_high"]     = or_high
    result["or_low"]      = or_low
    result["or_size"]     = or_size
    result["or_midpoint"] = or_midpoint

    # --- ATR filter ---
    if ORB_USE_ATR_FILTER and atr_value is not None and not pd.isna(atr_value):
        if or_size > ORB_ATR_MAX_MULT * atr_value:
            result["filter_reason"] = "atr_too_large"
            return result
        if or_size < ORB_ATR_MIN_MULT * atr_value:
            result["filter_reason"] = "atr_too_small"
            return result

    # --- Scan for breakout confirmation ---
    post_or = session_df.iloc[or_idx + 1:]
    cutoff_mask = (
        (post_or["timestamp_et"].dt.hour < ORB_TIME_CUTOFF_HOUR) |
        (
            (post_or["timestamp_et"].dt.hour == ORB_TIME_CUTOFF_HOUR) &
            (post_or["timestamp_et"].dt.minute <= ORB_TIME_CUTOFF_MINUTE)
        )
    )
    scannable = post_or[cutoff_mask]

    for idx in scannable.index:
        bar = session_df.iloc[idx]

        long_signal  = bar["close"] > or_high
        short_signal = bar["close"] < or_low

        if not long_signal and not short_signal:
            continue

        direction = "long" if long_signal else "short"

        # -------------------------------------------------------------------
        # ADX direction check for market entry mode
        # +DI > -DI = uptrend  → only take longs
        # -DI > +DI = downtrend → only take shorts
        # -------------------------------------------------------------------
        if session_entry_type == "market" and adx_data is not None:
            plus_di  = adx_data["plus_di"]
            minus_di = adx_data["minus_di"]
            if direction == "long" and minus_di >= plus_di:
                result["filter_reason"] = "adx_direction_mismatch"
                return result
            if direction == "short" and plus_di >= minus_di:
                result["filter_reason"] = "adx_direction_mismatch"
                return result

        # -------------------------------------------------------------------
        # MARKET ENTRY — enter at open of next bar, stop at 25% OR
        # -------------------------------------------------------------------
        if session_entry_type == "market":
            if idx + 1 >= len(session_df):
                result["filter_reason"] = "no_entry_bar"
                return result

            entry_bar   = session_df.iloc[idx + 1]
            entry_price = entry_bar["open"]

            if direction == "long":
                stop_price    = entry_price - (or_size * ORB_ADX_MARKET_STOP_PCT)
                risk_per_unit = entry_price - stop_price
            else:
                stop_price    = entry_price + (or_size * ORB_ADX_MARKET_STOP_PCT)
                risk_per_unit = stop_price - entry_price

            if risk_per_unit <= 0:
                continue

            target_price = (
                entry_price + ORB_REWARD_RISK * risk_per_unit
                if direction == "long"
                else entry_price - ORB_REWARD_RISK * risk_per_unit
            )

            result.update({
                "trade_taken":   True,
                "limit_pending": False,
                "direction":     direction,
                "entry_bar_idx": idx + 1,
                "entry_price":   entry_price,
                "stop_price":    stop_price,
                "target_price":  target_price,
                "entry_mode":    "market",
            })
            return result

        # -------------------------------------------------------------------
        # LIMIT ENTRY — place limit at OR midpoint after breakout confirmation
        # -------------------------------------------------------------------
        else:
            result.update({
                "trade_taken":          True,
                "limit_pending":        True,
                "direction":            direction,
                "confirmation_bar_idx": idx,
                "entry_price":          or_midpoint,
                "stop_price":           or_low if direction == "long" else or_high,
                "target_price":         None,
                "entry_mode":           "limit",
            })
            return result

    result["filter_reason"] = "time_expired"
    return result