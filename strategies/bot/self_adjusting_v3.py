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


def add_indicators(df: pd.DataFrame, params: Dict[str, Any]) -> pd.DataFrame:
    """Añade indicadores técnicos necesarios."""
    df = df.copy()

    # Usar los parámetros (en minúsculas) que vienen del backtester
    df['rsi'] = calculate_rsi(df['close'], params.get("rsi_period", 14))
    df['ema_fast'] = calculate_ema(df['close'], params["ema_fast_period"])
    df['ema_slow'] = calculate_ema(df['close'], params["ema_slow_period"])
    df['atr'] = calculate_atr(df, params.get("atr_period", 14))
    bb_high, bb_low = calculate_bollinger_bands(df['close'], params.get("bb_window", 20), params.get("bb_stddev", 2))
    df['bb_upper'] = bb_high
    df['bb_lower'] = bb_low

    df['bb_width'] = (df['bb_upper'] - df['bb_lower']) / (df['close'] + 1e-12)
    return df.dropna()


def self_adjusting_strategy_v3(
    df: pd.DataFrame, params: Dict[str, Any]
) -> Optional[Dict[str, Any]]:
    """
    Wrapper de la estrategia v3 para ser compatible con el backtester.
    """
    df = add_indicators(df.copy(), params)
    if len(df) < 100: # Necesita historial para el análisis de tendencia
        return None

    last = df.iloc[-1]
    prev = df.iloc[-2]

    # El backtester no simula la hora, así que omitimos este chequeo
    # if not (params['trading_start_hour'] <= current_hour < params['trading_end_hour']):
    #     return None
    if not (params.get('trading_start_hour', 0) <= datetime.now().hour < params.get('trading_end_hour', 24)):
        return None

    # --- 1️⃣ Análisis de estructura general ---
    ema_slope = (df['ema_slow'].iloc[-1] - df['ema_slow'].iloc[-10]) / df['ema_slow'].iloc[-10]
    atr_mean = df['atr'].tail(50).mean()
    atr_now = last['atr']
    trend_strength = abs(ema_slope) * (atr_now / (atr_mean + 1e-12))

    up_ratio = np.sum(df['close'].tail(30) > df['open'].tail(30)) / 30
    bias = "bullish" if up_ratio > 0.55 else ("bearish" if up_ratio < 0.45 else "neutral")

    # --- 2️⃣ Ajuste de duración según contexto ---
    if trend_strength > params['trend_strong_threshold']:
        duration = 10
    elif trend_strength > params['trend_medium_threshold']:
        duration = 5
    else:
        duration = 1

    # --- 3️⃣ Lógica de señal principal ---
    direction = None

    # Tendencia fuerte → continuación
    if trend_strength > params['trend_medium_threshold']:
        if ( # Señal de continuación alcista fortalecida
            bias == "bullish"
            and last['close'] > last['ema_slow']
            and last['ema_fast'] > last['ema_slow']  # tendencia alineada
            and last['rsi'] > 55
            and last['close'] > prev['high']          # rompe máximo anterior
        ):
            direction = "call"
        elif ( # Señal de continuación bajista fortalecida
            bias == "bearish"
            and last['close'] < last['ema_slow']
            and last['ema_fast'] < last['ema_slow']
            and last['rsi'] < 45
            and last['close'] < prev['low']
        ):
            direction = "put"

    # Mercado sin dirección → posible reversión
    elif ( # Reversión bajista con confirmación de momentum
        prev['close'] > prev['bb_upper'] - params['bb_touch_tolerance'] and
        last['rsi'] > params['rsi_overbought'] and
        last['close'] < prev['close']
        and last['ema_fast'] < prev['ema_fast']
    ):
        direction = "put"
    elif ( # Reversión alcista con confirmación de momentum
        prev['close'] < prev['bb_lower'] + params['bb_touch_tolerance'] and
        last['rsi'] < params['rsi_oversold'] and
        last['close'] > prev['close']
        and last['ema_fast'] > prev['ema_fast']
    ):
        direction = "call"

    if direction is None:
        return None

    # --- 4️⃣ Filtros de confirmación ---
    if last['bb_width'] < params['min_bb_width']:
        logger.debug(f"📉 [DESCARTADA] Mercado plano por BB width | bias={bias} | trend_strength={trend_strength:.6f} | RSI={last['rsi']:.2f}")
        return None
    if atr_now < atr_mean * params['atr_volatility_drop']:
        logger.debug(f"📉 [DESCARTADA] Mercado plano por ATR drop | bias={bias} | trend_strength={trend_strength:.6f} | RSI={last['rsi']:.2f}")
        return None

    logger.info(
        f"✅ Señal V3: {direction.upper()} | dur={duration}m | trend_strength={trend_strength:.6f} | bias={bias} | ema_slope={ema_slope:.6f}"
    )

    return {
        "strategy_name": "self_adjusting_v3",
        "direction": direction,
        "trend_strength": trend_strength,
        "bias": bias,
        "duration_minutes": duration,
        "ema_slope": ema_slope,
        "rsi": last["rsi"]
    }
