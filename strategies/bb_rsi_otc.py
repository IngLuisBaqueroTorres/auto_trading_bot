# strategies/bb_rsi_otc_trend.py
from typing import Optional, Dict, Any
import pandas as pd
from utils.indicators import calculate_rsi, calculate_bollinger_bands, calculate_ema, calculate_atr
from utils.logger import setup_logger

logger = setup_logger()

# ----------------- PARÁMETROS (ajustables) -----------------
RSI_NEAR_BUY = 55
RSI_NEAR_SELL = 45
MIN_SCORE_TO_ENTER = 0.50      # más permisivo en score, usamos confirmaciones
EMA_NEUTRAL_MARGIN_PCT = 0.001  # margen alrededor de EMA
MIN_BB_WIDTH = 0.0010           # más permisivo para no bloquear entradas
TRADING_START_HOUR = 7
TRADING_END_HOUR = 20

# Confirmación mínima: 2 de 3 (trend/momentum, bb/price, body/atr)
CONFIRMATIONS_TO_ENTER = 2

# Umbrales dinámicos ligados a ATR para evitar "micro-ruido"
ATR_BODY_MULTIPLIER = 0.5
ATR_STRONG_BODY_MULTIPLIER = 0.9

# Zona RSI neutra (evitar entradas inestables)
RSI_NEUTRAL_LOW = 48
RSI_NEUTRAL_HIGH = 52

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

def bb_rsi_otc_trend(df: pd.DataFrame, last_signal: Optional[str] = None, current_hour: Optional[int] = None) -> Optional[str]:
    """
    Versión agresiva experta:
    - Usa pendiente de EMA (no solo posición) + estructura (high/low)
    - Requiere 2 de 3 confirmaciones (trend/momentum, bollinger/price, body/atr)
    - Usa ATR para definir tamaños de vela mínimos y "fuerza"
    - Filtros anticagadas: no entrar contra vela previa fuerte, no entrar en RSI neutra
    """
    df = add_indicators(df).dropna()
    if len(df) < 60:
        return None

    last = df.iloc[-1]
    prev = df.iloc[-2]

    # Basic filters
    bb_width = (last['bb_high'] - last['bb_low']) / (last['close'] + 1e-12)
    if bb_width < MIN_BB_WIDTH:
        logger.debug(f"[strategy] BB width demasiado estrecho: {bb_width:.6f}")
        return None

    if current_hour is not None and not (TRADING_START_HOUR <= current_hour < TRADING_END_HOUR):
        logger.debug(f"[strategy] Fuera de horario: {current_hour}h")
        return None

    # EMA and its slope (pendiente)
    ema_now = last['ema200']
    ema_prev = df['ema200'].iloc[-2]
    ema_margin = ema_now * EMA_NEUTRAL_MARGIN_PCT
    ema_slope = (ema_now - ema_prev) / (ema_prev + 1e-12)  # relativo

    ema_up = ema_slope > 0
    ema_down = ema_slope < 0

    bullish_price_vs_ema = last['close'] > ema_now + ema_margin
    bearish_price_vs_ema = last['close'] < ema_now - ema_margin

    # Structure (highs / lows) - confirm direction
    high_now = last.get('high', last['close'])
    high_prev = prev.get('high', prev['close'])
    low_now = last.get('low', last['close'])
    low_prev = prev.get('low', prev['close'])

    up_structure = high_now > high_prev
    down_structure = low_now < low_prev

    # RSI momentum
    rsi_now = last['rsi']
    rsi_prev = prev['rsi']
    rsi_up = rsi_now > rsi_prev
    rsi_down = rsi_now < rsi_prev

    # ATR-based thresholds
    atr_now = max(last.get('atr', 1e-8), 1e-8)
    price_ref = df['close'].iloc[-20] if len(df) >= 20 else last['close']
    min_body_threshold = max(price_ref * 0.0005, atr_now * ATR_BODY_MULTIPLIER)
    strong_body_threshold = max(price_ref * 0.0010, atr_now * ATR_STRONG_BODY_MULTIPLIER)

    last_body = last['body']
    last_body_is_strong = last_body >= strong_body_threshold
    last_body_is_ok = last_body >= min_body_threshold

    # Avoid RSI neutral zone unless confirmations are very strong
    in_rsi_neutral = RSI_NEUTRAL_LOW < rsi_now < RSI_NEUTRAL_HIGH

    # Prev candle checks (anticagadas)
    prev_bullish = prev['close'] > prev['open']
    prev_bearish = prev['close'] < prev['open']
    prev_body = abs(prev['close'] - prev['open'])

    # Avoid entering against a strong previous candle
    prev_strong = prev_body >= strong_body_threshold

    # Build confirmations (2 of 3 logic)
    # For BUY confirmations
    confirmations_buy = 0
    reasons_buy = []

    # (A) Trend & momentum: price above EMA + ema rising + rsi rising + structure up
    cond_trend_buy = bullish_price_vs_ema and ema_up and rsi_up and up_structure
    if cond_trend_buy:
        confirmations_buy += 1
        reasons_buy.append("trend_momentum_ok")

    # (B) Price/BB confirmation: close above lower BB (shows reversion-to-mean or support)
    cond_bb_buy = last['close'] >= last['bb_low']
    if cond_bb_buy:
        confirmations_buy += 1
        reasons_buy.append("bb_support")

    # (C) Body/ATR confirmation: candle has strength
    cond_body_buy = last_body_is_ok
    if cond_body_buy:
        confirmations_buy += 1
        reasons_buy.append("body_ok")

    # For SELL confirmations
    confirmations_sell = 0
    reasons_sell = []

    cond_trend_sell = bearish_price_vs_ema and ema_down and rsi_down and down_structure
    if cond_trend_sell:
        confirmations_sell += 1
        reasons_sell.append("trend_momentum_ok")

    cond_bb_sell = last['close'] <= last['bb_high']
    if cond_bb_sell:
        confirmations_sell += 1
        reasons_sell.append("bb_resistance")

    cond_body_sell = last_body_is_ok
    if cond_body_sell:
        confirmations_sell += 1
        reasons_sell.append("body_ok")

    # Logging debug about constituents
    logger.debug(f"[strategy] rsi={rsi_now:.2f} rsi_prev={rsi_prev:.2f} ema_slope={ema_slope:.6f} "
                 f"bbw={bb_width:.6f} body={last_body:.6f} atr={atr_now:.6f} conf_buy={confirmations_buy} conf_sell={confirmations_sell}")

    # Anticagadas: no entrar si prev candle fue fuerte en contra
    def blocked_by_prev(signal: str) -> bool:
        if signal == "BUY" and prev_bearish and prev_strong:
            return True
        if signal == "SELL" and prev_bullish and prev_strong:
            return True
        return False

    # Avoid repeat same signal immediately
    def is_repetition(signal: str) -> bool:
        return last_signal == signal

    # Decide entry with confirmations (prefer BUY or SELL when confirmations >= CONFIRMATIONS_TO_ENTER)
    # Aggressive rule: if confirmations >= 2 and not blocked, enter.
    if confirmations_buy >= CONFIRMATIONS_TO_ENTER:
        if not blocked_by_prev("BUY") and not is_repetition("BUY"):
            # If in RSI neutral zone require a strong body to allow entry
            if (not in_rsi_neutral) or (in_rsi_neutral and last_body_is_strong):
                logger.info(f"✅ SIGNAL: BUY | conf={confirmations_buy} | reasons={reasons_buy}")
                return "BUY"

    if confirmations_sell >= CONFIRMATIONS_TO_ENTER:
        if not blocked_by_prev("SELL") and not is_repetition("SELL"):
            if (not in_rsi_neutral) or (in_rsi_neutral and last_body_is_strong):
                logger.info(f"✅ SIGNAL: SELL | conf={confirmations_sell} | reasons={reasons_sell}")
                return "SELL"

    # Fallback aggressive-ish: if trend+momentum present (cond_trend_buy/cond_trend_sell)
    # but confirmations < 2, allow entry only if body is strong and not blocked/repeated
    if cond_trend_buy and not blocked_by_prev("BUY") and not is_repetition("BUY"):
        if last_body_is_strong and (not in_rsi_neutral):
            logger.info(f"⚠️ FALLBACK BUY (trend present + strong body) | reasons={reasons_buy}")
            return "BUY"

    if cond_trend_sell and not blocked_by_prev("SELL") and not is_repetition("SELL"):
        if last_body_is_strong and (not in_rsi_neutral):
            logger.info(f"⚠️ FALLBACK SELL (trend present + strong body) | reasons={reasons_sell}")
            return "SELL"

    # Otherwise, no signal
    return None
