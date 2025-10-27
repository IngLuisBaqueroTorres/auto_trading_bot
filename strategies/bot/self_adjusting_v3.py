import json
import os
import logging
from datetime import datetime, timezone
from typing import Optional, Dict, Any
import pandas as pd
import numpy as np

from utils.indicators import (
    calculate_rsi,
    calculate_bollinger_bands,
    calculate_ema,
    calculate_atr
)

logger = logging.getLogger("TradingBot")

# --- CONFIGURACIÓN GLOBAL CON CARGA DINÁMICA ---
PARAMS = None

def get_params(force_reload: bool = False) -> dict:
    """Carga los parámetros de configuración desde JSON (con caché)."""
    global PARAMS
    if force_reload or PARAMS is None:
        config_path = os.path.join(os.path.dirname(__file__), 'self_adjusting_v3_config.json')
        if not os.path.exists(config_path):
            raise FileNotFoundError(f"No se encontró el archivo de configuración: {config_path}")
        with open(config_path, 'r') as f:
            PARAMS = json.load(f)
    return PARAMS


def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Añade indicadores técnicos necesarios."""
    params = get_params()
    df = df.copy()

    if 'rsi' not in df.columns:
        df['rsi'] = calculate_rsi(df['close'], 14)
    if 'ema_fast' not in df.columns:
        df['ema_fast'] = calculate_ema(df['close'], 14)
    if 'ema_slow' not in df.columns:
        df['ema_slow'] = calculate_ema(df['close'], 50)
    if 'atr' not in df.columns:
        df['atr'] = calculate_atr(df, 14)
    if 'bb_upper' not in df.columns:
        bb_high, bb_low = calculate_bollinger_bands(df['close'], 20, 2)
        df['bb_upper'] = bb_high
        df['bb_lower'] = bb_low

    df['bb_width'] = (df['bb_upper'] - df['bb_lower']) / (df['close'] + 1e-12)
    return df.dropna()


def self_adjusting_strategy_v3(
    df: pd.DataFrame,
    last_signal: Optional[str] = None,
    current_hour: Optional[int] = None
) -> Optional[Dict[str, Any]]:
    """
    Estrategia autoajustable v3 — detecta tendencias amplias y ajusta la duración.
    - Analiza las últimas 100 velas para estimar fuerza direccional.
    - Ajusta la duración esperada de la operación (1, 5 o 10 minutos).
    - Combina señales de reversión (v2) y continuación (v3 core).
    """
    params = get_params()
    df = add_indicators(df)
    if len(df) < 100:
        return None

    last = df.iloc[-1]
    prev = df.iloc[-2]

    now = datetime.now(timezone.utc)
    if current_hour is None:
        current_hour = now.hour

    if not (params['TRADING_START_HOUR'] <= current_hour < params['TRADING_END_HOUR']):
        return None

    # --- 1️⃣ Análisis de estructura general ---
    ema_slope = (df['ema_slow'].iloc[-1] - df['ema_slow'].iloc[-10]) / df['ema_slow'].iloc[-10]
    atr_mean = df['atr'].tail(50).mean()
    atr_now = last['atr']
    trend_strength = abs(ema_slope) * (atr_now / (atr_mean + 1e-12))

    up_ratio = np.sum(df['close'].tail(30) > df['open'].tail(30)) / 30
    bias = "bullish" if up_ratio > 0.55 else ("bearish" if up_ratio < 0.45 else "neutral")

    # --- 2️⃣ Ajuste de duración según contexto ---
    if trend_strength > params['TREND_STRONG_THRESHOLD']:
        duration = 10
    elif trend_strength > params['TREND_MEDIUM_THRESHOLD']:
        duration = 5
    else:
        duration = 1

    # --- 3️⃣ Lógica de señal principal ---
    direction = None

    # Tendencia fuerte → continuación
    if trend_strength > params['TREND_MEDIUM_THRESHOLD']:
        if (
            bias == "bullish" and
            last['close'] > last['ema_slow'] and
            last['rsi'] > 50 and
            last['close'] > prev['close']
        ):
            direction = "call"
        elif (
            bias == "bearish" and
            last['close'] < last['ema_slow'] and
            last['rsi'] < 50 and
            last['close'] < prev['close']
        ):
            direction = "put"

    # Mercado sin dirección → posible reversión
    elif (
        prev['close'] > prev['bb_upper'] - params['BB_TOUCH_TOLERANCE'] and
        last['rsi'] > params['RSI_OVERBOUGHT'] and
        last['close'] < prev['close']
    ):
        direction = "put"
    elif (
        prev['close'] < prev['bb_lower'] + params['BB_TOUCH_TOLERANCE'] and
        last['rsi'] < params['RSI_OVERSOLD'] and
        last['close'] > prev['close']
    ):
        direction = "call"

    if direction is None:
        return None

    # --- 4️⃣ Filtros de confirmación ---
    if last['bb_width'] < params['MIN_BB_WIDTH']:
        return None
    if atr_now < atr_mean * params['ATR_VOLATILITY_DROP']:
        return None

    logger.info(f"✅ Señal v3: {direction.upper()} | fuerza={trend_strength:.4f} | dur={duration}m | bias={bias}")

    return {
        "strategy_name": "self_adjusting_v3",
        "direction": direction,
        "trend_strength": trend_strength,
        "bias": bias,
        "duration_minutes": duration,
        "ema_slope": ema_slope,
        "rsi": last["rsi"],
        "atr": last["atr"],
        "timestamp": now
    }
