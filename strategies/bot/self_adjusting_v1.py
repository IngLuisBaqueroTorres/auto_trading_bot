# strategies/bot/self_adjusting_v1.py
import json
import os
from typing import Optional, Dict, Any
import logging
import pandas as pd
import datetime
from utils.indicators import (
    calculate_rsi,
    calculate_bollinger_bands,
    calculate_ema,
    calculate_atr
)

logger = logging.getLogger("TradingBot")

def load_config():
    """Carga los parámetros de la estrategia desde un archivo JSON."""
    # La ruta es relativa a este archivo
    config_path = os.path.join(os.path.dirname(__file__), 'self_adjusting_v1_config.json')
    if not os.path.exists(config_path):
        raise FileNotFoundError(f"No se encontró el archivo de configuración: {config_path}")
    with open(config_path, 'r') as f:
        return json.load(f)

PARAMS = load_config()

def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Añade los indicadores necesarios para la estrategia."""
    df = df.copy()
    if 'rsi' not in df.columns:
        df['rsi'] = calculate_rsi(df['close'], window=14)
    if 'bb_upper' not in df.columns:
        bb_high, bb_low = calculate_bollinger_bands(df['close'], window=20, std_dev=2)
        df['bb_upper'] = bb_high
        df['bb_lower'] = bb_low
    if 'ema' not in df.columns:
        df['ema'] = calculate_ema(df['close'], PARAMS['EMA_PERIOD'])
    if 'atr' not in df.columns:
        df['atr'] = calculate_atr(df, window=14)
    
    df['bb_width'] = (df['bb_upper'] - df['bb_lower']) / (df['close'] + 1e-12)
    return df

def self_adjusting_strategy_v1(
    df: pd.DataFrame,
    last_signal: Optional[str] = None,
    current_hour: Optional[int] = None
) -> Optional[Dict[str, Any]]:
    """
    Estrategia autoajustable que carga sus parámetros desde un archivo JSON.
    Basada en la lógica de BB + RSI + EMA.
    """
    df = add_indicators(df).dropna()
    if len(df) < PARAMS['EMA_PERIOD']:
        return None

    last = df.iloc[-1]
    prev = df.iloc[-2]

    now = datetime.datetime.now()
    if current_hour is None:
        current_hour = now.hour

    if not (PARAMS['TRADING_START_HOUR'] <= current_hour < PARAMS['TRADING_END_HOUR']):
        return None

    # -------- FILTROS DE VOLATILIDAD --------
    avg_atr = df['atr'].tail(20).mean()
    bb_width = last['bb_width']

    if bb_width < PARAMS['MIN_BB_WIDTH']:
        return None

    if last['atr'] < avg_atr * PARAMS['ATR_VOLATILITY_DROP']:
        return None

    # -------- LÓGICA PRINCIPAL --------
    confirmations = 0
    direction = None

    # Reversión bajista (PUT)
    if (
        prev['close'] > prev['bb_upper'] - PARAMS['BB_TOUCH_TOLERANCE'] and
        last['close'] < last['bb_upper'] - PARAMS['BB_TOUCH_TOLERANCE'] and
        last['rsi'] > PARAMS['RSI_OVERBOUGHT'] and
        last['close'] < last['ema']
    ):
        confirmations += 1
        direction = "put"

    # Reversión alcista (CALL)
    if (
        prev['close'] < prev['bb_lower'] + PARAMS['BB_TOUCH_TOLERANCE'] and
        last['close'] > last['bb_lower'] + PARAMS['BB_TOUCH_TOLERANCE'] and
        last['rsi'] < PARAMS['RSI_OVERSOLD'] and
        last['close'] > last['ema']
    ):
        confirmations += 1
        direction = "call"

    if confirmations < PARAMS['CONFIRMATIONS_TO_ENTER'] or direction is None:
        return None

    logger.info(
        f"✅ Señal Auto-Ajustable detectada: {direction.upper()} | RSI={last['rsi']:.2f} | BB width={bb_width:.4f}"
    )

    # Devolvemos un diccionario con todos los datos para el logger avanzado
    return {
        "strategy_name": "self_adjusting_v1",
        "direction": direction,
        "rsi": last['rsi'],
        "bb_width": bb_width,
        "ema": last['ema'],
        "atr": last['atr'],
        "timestamp": now
    }