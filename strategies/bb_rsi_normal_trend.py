from typing import Optional
import pandas as pd
from utils.indicators import calculate_rsi, calculate_bollinger_bands, calculate_ema, calculate_atr
from utils.logger import setup_logger

logger = setup_logger()

# ----------------- PARÁMETROS -----------------
# --- Umbrales y Filtros ---
MIN_SCORE_TO_ENTER = 1.0  # Aumentamos el umbral para exigir señales de mayor calidad.
EMA_NEUTRAL_MARGIN_PCT = 0.001
MIN_BB_WIDTH = 0.0020 # Relajamos un poco para permitir más operaciones en mercados menos volátiles.
TRADING_START_HOUR = 6
TRADING_END_HOUR = 20

# --- Pesos del Score ---
SCORE_PULLBACK_ENTRY = 1.3  # ✅ NUEVO: Señal de alta probabilidad, le damos el mayor peso.
SCORE_TREND_MOMENTUM = 0.8  # Reducimos ligeramente el peso de la condición general.
SCORE_RSI_ZONE = 0.4
SCORE_BB_CONFIRMATION = 0.3
SCORE_BODY_CONFIRMATION = 0.2 

# --- Umbrales de Indicadores ---
BODY_RATIO_THRESHOLD = 0.30 # Relajamos un poco para no ser tan estrictos con el tamaño de la vela.
RSI_PULLBACK_BUY = 48       # ✅ NUEVO: Nivel de RSI para detectar fin de retroceso alcista.
RSI_PULLBACK_SELL = 52      # ✅ NUEVO: Nivel de RSI para detectar fin de rebote bajista.
RSI_BULL_ZONE = 50
RSI_BEAR_ZONE = 50

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
    if 'ema20' not in df.columns: # Añadimos EMA20 para la confirmación de Bollinger
        df['ema20'] = calculate_ema(df['close'], window=20)
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

    # --- Condición 1: Entrada por Retroceso (Pullback) - ALTA PROBABILIDAD ---
    rsi_cross_up_pullback = prev['rsi'] < RSI_PULLBACK_BUY and last['rsi'] >= RSI_PULLBACK_BUY
    if bullish_trend and rsi_cross_up_pullback:
        score_buy += SCORE_PULLBACK_ENTRY
        reasons_buy.append(f"pullback_buy(rsi_cross_{RSI_PULLBACK_BUY})")

    rsi_cross_down_pullback = prev['rsi'] > RSI_PULLBACK_SELL and last['rsi'] <= RSI_PULLBACK_SELL
    if bearish_trend and rsi_cross_down_pullback:
        score_sell += SCORE_PULLBACK_ENTRY
        reasons_sell.append(f"pullback_sell(rsi_cross_{RSI_PULLBACK_SELL})")

    # --- Condición 2: Continuación de Tendencia y Momentum ---
    if bullish_trend and rsi_up:
        score_buy += SCORE_TREND_MOMENTUM
    if bearish_trend and rsi_down:
        score_sell += SCORE_TREND_MOMENTUM

    # Confirmación de zona RSI (Lógica mejorada)
    if last['rsi'] > RSI_BULL_ZONE:
        score_buy += SCORE_RSI_ZONE
        reasons_buy.append(f"rsi_in_bull_zone({last['rsi']:.1f})")
    if last['rsi'] < RSI_BEAR_ZONE:
        score_sell += SCORE_RSI_ZONE
        reasons_sell.append(f"rsi_in_bear_zone({last['rsi']:.1f})")

    # Confirmación Bollinger (Lógica mejorada usando EMA20)
    if last['close'] > last['ema20']:
        score_buy += SCORE_BB_CONFIRMATION
        reasons_buy.append("close_above_ema20")
    if last['close'] < last['ema20']:
        score_sell += SCORE_BB_CONFIRMATION
        reasons_sell.append("close_below_ema20")

    # Tamaño de vela
    body_ratio = last['body'] / (last['avg_body'] + 1e-12)
    if last['close'] > last['open'] and body_ratio >= BODY_RATIO_THRESHOLD:
        score_buy += SCORE_BODY_CONFIRMATION
        reasons_buy.append(f"bull_body({body_ratio:.2f})")
    elif last['close'] < last['open'] and body_ratio >= BODY_RATIO_THRESHOLD:
        score_sell += SCORE_BODY_CONFIRMATION
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
