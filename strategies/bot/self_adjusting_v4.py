# strategies/bot/self_adjusting_v4.py
import json
import os
from typing import Optional, Dict, Any
import logging
import pandas as pd
import numpy as np
from datetime import datetime

from utils.indicators import (
    calculate_rsi,
    calculate_bollinger_bands,
    calculate_ema,
    calculate_atr
)

logger = logging.getLogger("TradingBot")

def load_config():
    """Carga los parámetros de la estrategia desde su archivo JSON."""
    config_path = os.path.join(os.path.dirname(__file__), 'self_adjusting_v4_config.json')
    if not os.path.exists(config_path):
        raise FileNotFoundError(f"No se encontró el archivo de configuración: {config_path}")
    with open(config_path, 'r') as f:
        return json.load(f)

PARAMS = load_config()

def add_indicators(df: pd.DataFrame, params: Dict[str, Any]) -> pd.DataFrame:
    """Añade los indicadores necesarios para la estrategia."""
    df = df.copy()
    df['rsi'] = calculate_rsi(df['close'], params.get("rsi_period", 14))
    bb_high, bb_low = calculate_bollinger_bands(df['close'], params.get("bb_window", 20), params.get("bb_stddev", 2))
    df['bb_upper'] = bb_high
    df['bb_lower'] = bb_low
    df['ema_fast'] = calculate_ema(df['close'], params['ema_fast_period'])
    df['ema_slow'] = calculate_ema(df['close'], params['ema_slow_period'])
    df['atr'] = calculate_atr(df, params.get("atr_period", 14))
    df['bb_width'] = (df['bb_upper'] - df['bb_lower']) / df['close']
    return df

def get_market_bias(df: pd.DataFrame) -> str:
    """Determina el sesgo del mercado (bullish, bearish, neutral) basado en las EMAs."""
    last = df.iloc[-1]
    if last['ema_fast'] > last['ema_slow']:
        return "bullish"
    elif last['ema_fast'] < last['ema_slow']:
        return "bearish"
    else:
        return "neutral"

def self_adjusting_strategy_v4(
    df: pd.DataFrame, params: Dict[str, Any]
) -> Optional[Dict[str, Any]]:
    """
    Wrapper de la estrategia v4 para ser compatible con el backtester.
    """
    df_with_indicators = add_indicators(df.copy(), params).dropna()
    if len(df_with_indicators) < params['ema_slow_period']:
        return None

    last = df_with_indicators.iloc[-1]
    prev = df_with_indicators.iloc[-2] # Añadimos la vela previa para confirmación
    bias = get_market_bias(df_with_indicators) # Mover el cálculo del sesgo aquí para usarlo en los logs

    # El backtester no simula la hora, así que omitimos este chequeo
    if not (params.get('trading_start_hour', 0) <= datetime.now().hour < params.get('trading_end_hour', 24)):
        return None

    # --- Filtro de Volatilidad ---
    if last['bb_width'] < params['min_bb_width']:
        logger.debug(f"📉 [DESCARTADA] Mercado plano por BB width | bias={bias} | RSI={last['rsi']:.2f}")
        return None

    # --- Lógica de Señal ---
    direction = None
    # Señal de PUT (venta): Reversión a la media desde sobrecompra
    if (
        prev['close'] > prev['bb_upper'] and
        last['close'] < last['bb_upper'] and # Precio vuelve a entrar en la banda
        last['rsi'] > params['rsi_overbought']
    ):
        direction = "put"

    # Señal de CALL (compra): Reversión a la media desde sobreventa
    if (
        prev['close'] < prev['bb_lower'] and
        last['close'] > last['bb_lower'] and # Precio vuelve a entrar en la banda
        last['rsi'] < params['rsi_oversold']
    ):
        direction = "call"

    if direction is None:
        return None

    # --- FILTRO DE SESGO (LÓGICA V4 MÁS RELAJADA) ---
    if (direction == "put" and bias == "bullish" and last['rsi'] < 80) or \
       (direction == "call" and bias == "bearish" and last['rsi'] > 20):
        logger.debug(f"🚫 [DESCARTADA] Señal {direction} bloqueada por sesgo {bias} | RSI={last['rsi']:.2f}")
        return None

    logger.info(f"✅ Señal V4: {direction.upper()} | bias={bias} | RSI={last['rsi']:.2f} | BB width={last['bb_width']:.4f}")

    return {
        "strategy_name": "self_adjusting_v4",
        "direction": direction,
        "bias": bias,
        "rsi": last['rsi'],
        "bb_width": last['bb_width']
    }