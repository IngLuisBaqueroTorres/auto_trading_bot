from typing import Optional
import pandas as pd
from utils.indicators import calculate_rsi, calculate_bollinger_bands, calculate_ema, calculate_atr
from utils.logger import setup_logger

logger = setup_logger()

# ----------------- PARÁMETROS -----------------
RSI_NEAR_BUY = 52        # más conservador que OTC
RSI_NEAR_SELL = 48
MIN_SCORE_TO_ENTER = 0.65  # más alto que en OTC
EMA_NEUTRAL_MARGIN_PCT = 0.0015
MIN_BB_WIDTH = 0.0025
TRADING_START_HOUR = 6
TRADING_END_HOUR = 18

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

def bb_rsi_normal_trend(df: pd.DataFrame, last_signal: Optional[str] = None, current_hour: Optional[int] = None) -> Optional[str]:
    """
    Estrategia enfocada en mercados normales:
    - Confirmaciones más estrictas que en OTC
    - Evita sobre-operar en zonas laterales
    - Sin fallback agresivo
    """
    df = add_indicators(df).dropna()
    if len(df) < 60:
        return None

    last = df.iloc[-1]
    prev = df.iloc[-2]

    # ----------- Filtros básicos ----------- 
    bb_width = (last['bb_high'] - last['bb_low']) / (last['close'] + 1e-12)
    if bb_width < MIN_BB_WIDTH:
        logger.debug(f"BB width demasiado estrecho: {bb_width:.5f}")
        return None

    if current_hour is not None and not (TRADING_START_HOUR <= current_hour < TRADING_END_HOUR):
        logger.debug(f"Fuera de horario de trading: {current_hour}h")
        return None

    # ----------- Tendencia con EMA ---------
    ema_margin = last['ema200'] * EMA_NEUTRAL_MARGIN_PCT
    bullish_trend = last['close'] > last['ema200'] + ema_margin
    bearish_trend = last['close'] < last['ema200'] - ema_margin

    # ----------- RSI Momentum -------------
    rsi_up = last['rsi'] > prev['rsi']
    rsi_down = last['rsi'] < prev['rsi']

    # ----------- Score ----------
    score_buy = 0.0
    score_sell = 0.0
    reasons_buy, reasons_sell = [], []

    # Tendencia principal
    if bullish_trend and rsi_up:
        score_buy += 1.0
        reasons_buy.append("trend_up + rsi_up")
    if bearish_trend and rsi_down:
        score_sell += 1.0
        reasons_sell.append("trend_down + rsi_down")

    # RSI relajado (pero más estricto que OTC)
    if last['rsi'] <= RSI_NEAR_BUY:
        score_buy += 0.5
        reasons_buy.append(f"rsi_near_buy({last['rsi']:.1f})")
    if last['rsi'] >= RSI_NEAR_SELL:
        score_sell += 0.5
        reasons_sell.append(f"rsi_near_sell({last['rsi']:.1f})")

    # Confirmación Bollinger
    if last['close'] >= last['bb_low']:
        score_buy += 0.3
        reasons_buy.append("close_above_bb_low")
    if last['close'] <= last['bb_high']:
        score_sell += 0.3
        reasons_sell.append("close_below_bb_high")

    # Tamaño de vela
    body_ratio = last['body'] / (last['avg_body'] + 1e-12)
    if last['close'] > last['open'] and body_ratio >= 0.5:
        score_buy += 0.2
        reasons_buy.append(f"bull_body({body_ratio:.2f})")
    elif last['close'] < last['open'] and body_ratio >= 0.5:
        score_sell += 0.2
        reasons_sell.append(f"bear_body({body_ratio:.2f})")

    # ----------- Decisión ----------
    if score_buy > score_sell and score_buy >= MIN_SCORE_TO_ENTER:
        if last_signal != "BUY":
            logger.info(f"✅ SIGNAL: BUY | score={score_buy:.2f} | reasons={reasons_buy}")
            return "BUY"
    elif score_sell > score_buy and score_sell >= MIN_SCORE_TO_ENTER:
        if last_signal != "SELL":
            logger.info(f"✅ SIGNAL: SELL | score={score_sell:.2f} | reasons={reasons_sell}")
            return "SELL"

    # No hay señal
    return None
