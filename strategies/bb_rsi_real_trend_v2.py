# strategies/bb_rsi_real_trend_v2.py
from typing import Optional
import pandas as pd
from datetime import datetime
from utils.indicators import calculate_rsi, calculate_bollinger_bands, calculate_ema, calculate_atr
from utils.logger import setup_logger

logger = setup_logger()

# ----------------- PARÁMETROS PRINCIPALES -----------------
TRADING_START_HOUR = 8
TRADING_END_HOUR = 12

# --- Filtros dinámicos ---
MIN_BB_WIDTH = 0.0020           # Evita operar en compresión
ATR_VOLATILITY_FACTOR = 0.8     # ATR actual debe ser >= 80% del promedio
EMA_NEUTRAL_MARGIN_PCT = 0.001  # Margen para tendencia neutra

# --- Umbrales RSI ---
RSI_PULLBACK_BUY = 48
RSI_PULLBACK_SELL = 52
RSI_BULL_ZONE = 50
RSI_BEAR_ZONE = 50

# --- Ponderación de Score ---
MIN_SCORE_TO_ENTER = 1.2
SCORE_PULLBACK_ENTRY = 1.3
SCORE_TREND_MOMENTUM = 0.8
SCORE_RSI_ZONE = 0.4
SCORE_BB_CONFIRMATION = 0.3
SCORE_BODY_CONFIRMATION = 0.2
PENALTY_CONTRADICTION = 0.4   # Penalización si RSI o cuerpo contradicen la tendencia

# --- Umbral cuerpo vela ---
BODY_RATIO_THRESHOLD = 0.30


# ===========================================================
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
    if 'ema20' not in df.columns:
        df['ema20'] = calculate_ema(df['close'], window=20)
    if 'atr' not in df.columns:
        df['atr'] = calculate_atr(df, window=14)

    df['body'] = (df['close'] - df['open']).abs()
    df['avg_body'] = df['body'].rolling(20, min_periods=1).mean()
    return df


# ===========================================================
def bb_rsi_real_trend_v2(df: pd.DataFrame, last_signal: Optional[str] = None, current_hour: Optional[int] = None) -> Optional[str]:
    """
    Estrategia orientada al mercado real (8–12h):
    - Filtra horas muertas entre 9:30 y 10:30
    - Evita operar sin volatilidad (ATR y BB width)
    - Priorización de tendencia y retrocesos (pullbacks)
    - Penaliza señales contradictorias
    """
    df = add_indicators(df).dropna()
    if len(df) < 60:
        return None

    last = df.iloc[-1]
    prev = df.iloc[-2]

    # ===========================================================
    # 1️⃣ HORARIO DINÁMICO
    if current_hour is None:
        current_hour = datetime.now().hour
    current_minute = datetime.now().minute
    if not (TRADING_START_HOUR <= current_hour < TRADING_END_HOUR):
        logger.debug(f"[v2] Fuera de horario permitido ({current_hour}h)")
        return None
    if 9 <= current_hour < 10 and 15 <= current_minute <= 45:
        logger.debug("[v2] Hora muerta (9:15–9:45), evitando sobreoperar")
        return None

    # ===========================================================
    # 2️⃣ FILTROS DE VOLATILIDAD
    bb_width = (last['bb_high'] - last['bb_low']) / (last['close'] + 1e-12)
    atr_now = last['atr']
    atr_avg = df['atr'].tail(20).mean()
    if bb_width < MIN_BB_WIDTH:
        logger.debug(f"[v2] Banda de Bollinger estrecha (BB={bb_width:.6f})")
        return None
    if atr_now < atr_avg * ATR_VOLATILITY_FACTOR:
        logger.debug(f"[v2] ATR bajo (ATR={atr_now:.5f}, avg={atr_avg:.5f})")
        return None

    # ===========================================================
    # 3️⃣ TENDENCIA PRINCIPAL
    ema_margin = last['ema200'] * EMA_NEUTRAL_MARGIN_PCT
    bullish_trend = last['close'] > last['ema200'] + ema_margin
    bearish_trend = last['close'] < last['ema200'] - ema_margin

    # ===========================================================
    # 4️⃣ MOMENTUM RSI
    rsi_up = last['rsi'] > prev['rsi']
    rsi_down = last['rsi'] < prev['rsi']

    # ===========================================================
    # 5️⃣ SCORE ESTRUCTURADO
    score_buy, score_sell = 0.0, 0.0
    reasons_buy, reasons_sell = [], []

    # --- Pullback entries ---
    if bullish_trend and prev['rsi'] < RSI_PULLBACK_BUY <= last['rsi']:
        score_buy += SCORE_PULLBACK_ENTRY
        reasons_buy.append(f"pullback_buy(rsi_cross_{RSI_PULLBACK_BUY})")

    if bearish_trend and prev['rsi'] > RSI_PULLBACK_SELL >= last['rsi']:
        score_sell += SCORE_PULLBACK_ENTRY
        reasons_sell.append(f"pullback_sell(rsi_cross_{RSI_PULLBACK_SELL})")

    # --- Continuación de tendencia ---
    if bullish_trend and rsi_up:
        score_buy += SCORE_TREND_MOMENTUM
        reasons_buy.append("trend_continuation_up")

    if bearish_trend and rsi_down:
        score_sell += SCORE_TREND_MOMENTUM
        reasons_sell.append("trend_continuation_down")

    # --- RSI zones ---
    if last['rsi'] > RSI_BULL_ZONE:
        score_buy += SCORE_RSI_ZONE
    if last['rsi'] < RSI_BEAR_ZONE:
        score_sell += SCORE_RSI_ZONE

    # --- Confirmación EMA20 / Bollinger ---
    if last['close'] > last['ema20']:
        score_buy += SCORE_BB_CONFIRMATION
    if last['close'] < last['ema20']:
        score_sell += SCORE_BB_CONFIRMATION

    # --- Cuerpo de vela ---
    body_ratio = last['body'] / (last['avg_body'] + 1e-12)
    if last['close'] > last['open'] and body_ratio >= BODY_RATIO_THRESHOLD:
        score_buy += SCORE_BODY_CONFIRMATION
    elif last['close'] < last['open'] and body_ratio >= BODY_RATIO_THRESHOLD:
        score_sell += SCORE_BODY_CONFIRMATION

    # ===========================================================
    # 6️⃣ PENALIZACIONES
    if bullish_trend and rsi_down:
        score_buy -= PENALTY_CONTRADICTION
        reasons_buy.append("penalty_rsi_contrary")
    if bearish_trend and rsi_up:
        score_sell -= PENALTY_CONTRADICTION
        reasons_sell.append("penalty_rsi_contrary")

    # ===========================================================
    # 7️⃣ DECISIÓN FINAL
    logger.debug(f"[v2] BUY={score_buy:.2f} ({reasons_buy}) | SELL={score_sell:.2f} ({reasons_sell})")

    if score_buy >= MIN_SCORE_TO_ENTER and score_buy > score_sell:
        if last_signal != "BUY":
            logger.info(f"✅ SIGNAL: BUY (Real Trend v2) | score={score_buy:.2f} | reasons={reasons_buy}")
            return "BUY"

    if score_sell >= MIN_SCORE_TO_ENTER and score_sell > score_buy:
        if last_signal != "SELL":
            logger.info(f"✅ SIGNAL: SELL (Real Trend v2) | score={score_sell:.2f} | reasons={reasons_sell}")
            return "SELL"

    return None
