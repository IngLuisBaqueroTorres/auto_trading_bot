# strategies/bot/self_adjusting_v2.py
import json
import os
from typing import Optional, Dict, Any
import logging
import pandas as pd
from datetime import datetime, timezone

from utils.indicators import (
    calculate_rsi,
    calculate_bollinger_bands,
    calculate_ema,
    calculate_atr
)

logger = logging.getLogger("TradingBot")

# --- Nivel 1: Carga de parámetros bajo demanda ---
PARAMS = None

def get_params(force_reload: bool = False) -> dict:
    """Carga los parámetros desde el archivo JSON, con caché."""
    global PARAMS
    if force_reload or PARAMS is None:
        config_path = os.path.join(os.path.dirname(__file__), 'self_adjusting_v2_config.json')
        if not os.path.exists(config_path):
            raise FileNotFoundError(f"No se encontró el archivo de configuración: {config_path}")
        with open(config_path, 'r') as f:
            PARAMS = json.load(f)
    return PARAMS

def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Añade los indicadores necesarios para la estrategia."""
    params = get_params()
    df = df.copy()
    if 'rsi' not in df.columns:
        df['rsi'] = calculate_rsi(df['close'], window=14)
    if 'bb_upper' not in df.columns:
        bb_high, bb_low = calculate_bollinger_bands(df['close'], window=20, std_dev=2)
        df['bb_upper'] = bb_high
        df['bb_lower'] = bb_low
    if 'ema' not in df.columns:
        df['ema'] = calculate_ema(df['close'], params['EMA_PERIOD'])
    if 'atr' not in df.columns:
        df['atr'] = calculate_atr(df, window=14)
    
    df['bb_width'] = (df['bb_upper'] - df['bb_lower']) / (df['close'] + 1e-12)
    return df

def self_adjusting_strategy_v2(
    df: pd.DataFrame,
    last_signal: Optional[str] = None,
    current_hour: Optional[int] = None
) -> Optional[Dict[str, Any]]:
    """
    Estrategia autoajustable v2 con mejoras de estabilidad y lógica.
    - Carga de parámetros bajo demanda.
    - Lógica de entrada y filtro de tendencia separados.
    - Validación de fuerza de ruptura y contexto RSI.
    """
    params = get_params()
    df = add_indicators(df).dropna()
    if len(df) < params['EMA_PERIOD']:
        return None

    last = df.iloc[-1]
    prev = df.iloc[-2]

    # --- Nivel 1: Uso de UTC para el tiempo ---
    now = datetime.now(timezone.utc)
    if current_hour is None:
        current_hour = now.hour

    if not (params['TRADING_START_HOUR'] <= current_hour < params['TRADING_END_HOUR']):
        return None

    # --- Nivel 2: Filtros de contexto y volatilidad ---
    if last['bb_width'] < params['MIN_BB_WIDTH']: return None
    if last['atr'] < df['atr'].tail(20).mean() * params['ATR_VOLATILITY_DROP']: return None
    
    candle_range = abs(last['close'] - last['open'])
    if candle_range < last['atr'] * 0.5: return None # Movimiento débil

    direction = None

    # --- Nivel 2: Lógica de entrada mejorada ---
    # Reversión bajista (PUT)
    if (
        prev['close'] > prev['bb_upper'] - params['BB_TOUCH_TOLERANCE'] and
        last['rsi'] > params['RSI_OVERBOUGHT'] and
        last['close'] < prev['close'] # Vela de confirmación bajista
    ):
        direction = "put"

    # Reversión alcista (CALL)
    if (
        prev['close'] < prev['bb_lower'] + params['BB_TOUCH_TOLERANCE'] and
        last['rsi'] < params['RSI_OVERSOLD'] and
        last['close'] > prev['close'] # Vela de confirmación alcista
    ):
        direction = "call"

    if direction is None:
        return None

    # --- Nivel 2: Filtros post-señal ---
    # Filtro de tendencia con EMA
    if (direction == "call" and last['close'] < last['ema']) or \
       (direction == "put" and last['close'] > last['ema']):
        return None

    # Filtro de persistencia RSI
    rsi_trend = df['rsi'].tail(5).mean()
    if (direction == "call" and rsi_trend < 25) or \
       (direction == "put" and rsi_trend > 75):
        return None

    logger.info(f"✅ Señal Auto-Ajustable v2: {direction.upper()} | RSI={last['rsi']:.2f} | BB width={last['bb_width']:.4f}")

    return {
        "strategy_name": "self_adjusting_v2",
        "direction": direction,
        "rsi": last['rsi'],
        "bb_width": last['bb_width'],
        "ema": last['ema'],
        "atr": last['atr'],
        "timestamp": now
    }