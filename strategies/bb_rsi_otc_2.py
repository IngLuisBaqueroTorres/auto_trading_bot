# strategies/bb_rsi_otc_trend.py (versión ajustada para más entradas)
from typing import Optional, Dict, Any
import time
import pandas as pd
from utils.indicators import calculate_rsi, calculate_bollinger_bands, calculate_ema, calculate_atr
from utils.logger import setup_logger

logger = setup_logger()

# ----------------- PARÁMETROS (ajustables) -----------------
RSI_NEAR_BUY = 58                # antes 60 (más flexible para BUY)
RSI_NEAR_SELL = 42               # antes 40 (más flexible para SELL)
MIN_SCORE_TO_ENTER = 0.65
EMA_NEUTRAL_MARGIN_PCT = 0.0008
MIN_BB_WIDTH = 0.0015
TRADING_START_HOUR = 7
TRADING_END_HOUR = 20

# BAJAMOS confirmaciones de 3 → 2
CONFIRMATIONS_TO_ENTER = 2

ATR_BODY_MULTIPLIER = 0.7
ATR_STRONG_BODY_MULTIPLIER = 1.2

RSI_NEUTRAL_LOW = 47
RSI_NEUTRAL_HIGH = 53

EMA_SLOPE_MIN = 0.0004

# Reducimos cooldown de 3 min → 1 min
MIN_SECONDS_BETWEEN_TRADES = 60
MAX_TRADES_PER_HOUR = 6

PRICE_EDGE_PCT = 0.15

# ----------------- FUNCIONES -----------------
def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    if 'rsi' not in df.columns:
        df['rsi'] = calculate_rsi(df['close'], window=14)
    if 'bb_high' not in df.columns or 'bb_low' not in df.columns:
        bb_high, bb_low = calculate_bollinger_bands(df['close'], window=20)
        df['bb_high'] = bb_high
        df['bb_low'] = bb_low
    if 'ema200' not in df.columns:
        df['ema200'] = calculate_ema(df['close'], window=200)
    if 'atr' not in df.columns:
        df['atr'] = calculate_atr(df, window=14)
    df['body'] = (df['close'] - df['open']).abs()
    df['avg_body'] = df['body'].rolling(20, min_periods=1).mean()
    return df

def _price_within_edge_of_bb(last_close: float, bb_low: float, bb_high: float, edge_pct: float) -> Dict[str, bool]:
    width = bb_high - bb_low
    if width <= 0:
        return {'near_low': False, 'near_high': False}
    dist_low = last_close - bb_low
    dist_high = bb_high - last_close
    return {
        'near_low': (dist_low / width) <= edge_pct,
        'near_high': (dist_high / width) <= edge_pct
    }

def bb_rsi_otc_trend(
    df: pd.DataFrame,
    last_signal: Optional[str] = None,
    current_hour: Optional[int] = None,
    last_trade_timestamp: Optional[float] = None,
    trades_in_last_hour: int = 0
) -> Optional[str]:

    df = add_indicators(df).dropna()
    if len(df) < 60:
        return None

    last = df.iloc[-1]
    prev = df.iloc[-2]

    bb_width = (last['bb_high'] - last['bb_low']) / (last['close'] + 1e-12)
    if bb_width < MIN_BB_WIDTH:
        return None

    if current_hour is not None and not (TRADING_START_HOUR <= current_hour < TRADING_END_HOUR):
        return None

    now_ts = time.time()
    if last_trade_timestamp is not None:
        if (now_ts - last_trade_timestamp) < MIN_SECONDS_BETWEEN_TRADES:
            return None
    if trades_in_last_hour >= MAX_TRADES_PER_HOUR:
        return None

    ema_now = last['ema200']
    ema_prev = df['ema200'].iloc[-2]
    ema_slope = (ema_now - ema_prev) / (ema_prev + 1e-12)
    ema_up = ema_slope > EMA_SLOPE_MIN
    ema_down = ema_slope < -EMA_SLOPE_MIN
    ema_neutral = not (ema_up or ema_down)

    bullish_price_vs_ema = last['close'] > ema_now + ema_now * EMA_NEUTRAL_MARGIN_PCT
    bearish_price_vs_ema = last['close'] < ema_now - ema_now * EMA_NEUTRAL_MARGIN_PCT

    up_structure = (last.get('high', last['close']) > prev.get('high', prev['close']))
    down_structure = (last.get('low', last['close']) < prev.get('low', prev['close']))

    rsi_now = last['rsi']
    rsi_prev = prev['rsi']
    rsi_up = rsi_now > rsi_prev
    rsi_down = rsi_now < rsi_prev

    atr_now = max(last.get('atr', 1e-8), 1e-8)
    price_ref = df['close'].iloc[-20] if len(df) >= 20 else last['close']
    min_body_threshold = max(price_ref * 0.0007, atr_now * ATR_BODY_MULTIPLIER)
    strong_body_threshold = max(price_ref * 0.0015, atr_now * ATR_STRONG_BODY_MULTIPLIER)

    last_body = last['body']
    last_body_is_strong = last_body >= strong_body_threshold
    last_body_is_ok = last_body >= min_body_threshold

    in_rsi_neutral = RSI_NEUTRAL_LOW < rsi_now < RSI_NEUTRAL_HIGH

    prev_bullish = prev['close'] > prev['open']
    prev_bearish = prev['close'] < prev['open']
    prev_body = abs(prev['close'] - prev['open'])
    prev_strong = prev_body >= strong_body_threshold

    edge_info = _price_within_edge_of_bb(last['close'], last['bb_low'], last['bb_high'], PRICE_EDGE_PCT)
    near_low = edge_info['near_low']
    near_high = edge_info['near_high']

    confirmations_buy = 0
    reasons_buy = []

    cond_trend_buy = bullish_price_vs_ema and ema_up and rsi_up and up_structure and not ema_neutral
    if cond_trend_buy:
        confirmations_buy += 1
        reasons_buy.append("trend_momentum_ok")

    cond_bb_buy = near_low
    if cond_bb_buy:
        confirmations_buy += 1
        reasons_buy.append("bb_edge_support")

    cond_body_buy = last_body_is_ok
    if cond_body_buy:
        confirmations_buy += 1
        reasons_buy.append("body_ok")

    confirmations_sell = 0
    reasons_sell = []

    cond_trend_sell = bearish_price_vs_ema and ema_down and rsi_down and down_structure and not ema_neutral
    if cond_trend_sell:
        confirmations_sell += 1
        reasons_sell.append("trend_momentum_ok")

    cond_bb_sell = near_high
    if cond_bb_sell:
        confirmations_sell += 1
        reasons_sell.append("bb_edge_resistance")

    cond_body_sell = last_body_is_ok
    if cond_body_sell:
        confirmations_sell += 1
        reasons_sell.append("body_ok")

    def blocked_by_prev(signal: str) -> bool:
        if signal == "BUY" and prev_bearish and prev_strong:
            return True
        if signal == "SELL" and prev_bullish and prev_strong:
            return True
        return False

    def is_repetition(signal: str) -> bool:
        return last_signal == signal

    if confirmations_buy >= CONFIRMATIONS_TO_ENTER:
        if not blocked_by_prev("BUY") and not is_repetition("BUY"):
            if (not in_rsi_neutral) or (in_rsi_neutral and last_body_is_strong):
                logger.info(f"✅ SIGNAL: BUY | conf={confirmations_buy} | reasons={reasons_buy}")
                return "BUY"

    if confirmations_sell >= CONFIRMATIONS_TO_ENTER:
        if not blocked_by_prev("SELL") and not is_repetition("SELL"):
            if (not in_rsi_neutral) or (in_rsi_neutral and last_body_is_strong):
                logger.info(f"✅ SIGNAL: SELL | conf={confirmations_sell} | reasons={reasons_sell}")
                return "SELL"

    if confirmations_buy >= 2 and last_body_is_strong and near_low and not blocked_by_prev("BUY") and not is_repetition("BUY"):
        logger.info(f"⚠️ FALLBACK BUY (2/3 + strong body + edge) | reasons={reasons_buy}")
        return "BUY"

    if confirmations_sell >= 2 and last_body_is_strong and near_high and not blocked_by_prev("SELL") and not is_repetition("SELL"):
        logger.info(f"⚠️ FALLBACK SELL (2/3 + strong body + edge) | reasons={reasons_sell}")
        return "SELL"

    return None
