"""
config_example.py

Example configuration for the ORB (Opening Range Breakout) backtest engine.
Rename to config.py and adjust values for your own use.

Values shown here are illustrative defaults, not tuned/live parameters.
"""

# --- Data ---
ORB_DATA_FILE        = "data/QQQ_15Min.csv"   # CSV with columns: timestamp, open, high, low, close
ORB_RUN_NAME          = "orb_example_run"

# --- Risk & Reward ---
ORB_RISK_PER_TRADE    = 0.01      # 1% of equity risked per trade
ORB_REWARD_RISK        = 1.5       # reward:risk ratio for target placement

# --- Train/Test Split ---
ORB_TRAIN_YEARS        = 4         # years of data from the start used for training
ORB_MODE                = "train"   # "train" (before split) | "test" (after split)

# --- Entry Window ---
ORB_TIME_CUTOFF_HOUR    = 11        # last allowed breakout confirmation bar opens at this hour (ET)
ORB_TIME_CUTOFF_MINUTE  = 30        # and this minute

# --- Entry Type ---
ORB_ENTRY_TYPE = "limit"   # "market" | "limit"
                             # market = enter at open of bar after breakout confirmation
                             # limit  = enter at opening-range midpoint, cancel if unfilled by cutoff

# --- Execution Costs ---
ORB_SLIPPAGE    = 0.001    # applied to market entries only
ORB_COMMISSION  = 0.001    # applied to all entries

# --- ATR Filter (optional) ---
ORB_USE_ATR_FILTER = False
ORB_ATR_PERIOD       = 14
ORB_ATR_MIN_MULT     = 1.0     # skip session if opening range is smaller than this multiple of ATR
ORB_ATR_MAX_MULT     = 3.0     # skip session if opening range is larger than this multiple of ATR

# --- Directional Bias Filter (optional) ---
ORB_USE_BIAS_FILTER = False
# Requires a bias_history loader returning {"date": "long"|"short"|"neutral"} per session.
# See bias/ module for an example implementation pattern.

# --- Gap Filter (optional) ---
ORB_USE_GAP_FILTER       = False
ORB_GAP_LONG_THRESHOLD   = 0.0   # % gap up minimum to allow longs
ORB_GAP_SHORT_THRESHOLD  = 0.0   # % gap down minimum to allow shorts

# --- ADX Regime Filter (optional) ---
ORB_USE_ADX_FILTER       = False
ORB_ADX_PERIOD            = 14
ORB_ADX_LOW_THRESHOLD     = 20      # below this = use limit entry
ORB_ADX_HIGH_THRESHOLD    = 25      # above this = use market entry
ORB_ADX_MARKET_STOP_PCT   = 0.50    # stop at this % of opening-range size for market entries
ORB_ADX_MARKET_RISK        = 0.005   # risk per trade specifically for ADX market-mode entries