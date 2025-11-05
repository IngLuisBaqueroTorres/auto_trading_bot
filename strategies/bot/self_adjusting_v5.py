# strategies/bot/self_adjusting_v5.py
import pandas as pd
import numpy as np
import json
import os
from datetime import datetime

try:
    import talib as ta
except ImportError:
    raise ImportError("Instala: pip install ta-lib")

PARAMS_V5 = None

def get_params_v5(force_reload: bool = False) -> dict:
    """Carga los parámetros de configuración desde JSON (con caché)."""
    global PARAMS_V5
    if force_reload or PARAMS_V5 is None:
        config_path = os.path.join(os.path.dirname(__file__), 'self_adjusting_v5_config.json')
        with open(config_path, 'r') as f:
            PARAMS_V5 = json.load(f)
    return PARAMS_V5

def add_indicators(df: pd.DataFrame, params: dict) -> pd.DataFrame:
    close = df['close'].values
    high = df['high'].values
    low = df['low'].values

    p = params

    # EMAs
    df['ema_fast'] = ta.EMA(close, timeperiod=p.get('ema_fast_period', 9))
    df['ema_slow'] = ta.EMA(close, timeperiod=p.get('ema_slow_period', 21))
    df['ema_trend'] = ta.EMA(close, timeperiod=p.get('ema_trend_period', 200))

    # RSI
    df['rsi'] = ta.RSI(close, timeperiod=p.get('rsi_period', 13))

    # Bollinger Bands
    bb_window = p.get('bb_window', 30)
    bb_std = p.get('bb_stddev', 2.0)
    upper, middle, lower = ta.BBANDS(close, timeperiod=bb_window, nbdevup=bb_std, nbdevdn=bb_std)
    df['bb_upper'] = upper
    df['bb_lower'] = lower
    df['bb_middle'] = middle
    df['bb_width'] = np.where(middle != 0, (upper - lower) / middle, 0)

    return df


def self_adjusting_strategy_v5(data: pd.DataFrame, params: dict = None, last_signal: str = None, current_hour: int = None):
    # Si los parámetros no se pasan, los carga desde el archivo.
    # Esto da compatibilidad con main.py y con el backtester.
    if params is None:
        params = get_params_v5()

    if len(data) < 200:
        return None

    # --- FILTRO DE HORARIO ---
    # Usar la hora que viene del main.py para consistencia con backtesting
    if current_hour is None:
        current_hour = datetime.now().hour

    start_hour = params.get("start_hour", 8)   # hora de inicio (por defecto 8)
    end_hour = params.get("end_hour", 20)      # hora de fin (por defecto 20)

    if not (start_hour <= current_hour < end_hour):
        return None  # fuera del horario permitido

    df = data.copy()
    df = add_indicators(df, params)
    candle = df.iloc[-1]

    # --- PARÁMETROS ---
    overbought = params.get('rsi_overbought', 60)
    oversold = params.get('rsi_oversold', 40)
    min_bb_width = params.get('min_bb_width', 0.0003)
    min_bb_trend = params.get('min_bb_width_trend', 0.0008)
    conf_needed = params.get('confirmations_to_enter', 1)
    lookback_rsi = 10
    lookback_cross = 3

    # --- FILTROS ---
    if pd.isna(candle['rsi']) or pd.isna(candle['ema_trend']):
        return None

    if candle['bb_width'] < min_bb_trend:
        return None  # evitar operar en rango estrecho

    # --- TENDENCIA (EMA 200) ---
    price_above_trend = candle['close'] > candle['ema_trend']
    price_below_trend = candle['close'] < candle['ema_trend']

    # --- CRUCE RECIENTE DE EMA ---
    recent = df.tail(lookback_cross)
    ema_cross_up = any(
        recent.iloc[i-1]['ema_fast'] <= recent.iloc[i-1]['ema_slow'] and
        recent.iloc[i]['ema_fast'] > recent.iloc[i]['ema_slow']
        for i in range(1, len(recent))
    )
    ema_cross_down = any(
        recent.iloc[i-1]['ema_fast'] >= recent.iloc[i-1]['ema_slow'] and
        recent.iloc[i]['ema_fast'] < recent.iloc[i]['ema_slow']
        for i in range(1, len(recent))
    )

    # --- CONFIRMACIONES RSI ---
    recent_rsi = df.tail(lookback_rsi)
    put_confirm = sum(
        1 for _, row in recent_rsi.iterrows()
        if row['rsi'] > overbought and row['bb_width'] > min_bb_width
    )
    call_confirm = sum(
        1 for _, row in recent_rsi.iterrows()
        if row['rsi'] < oversold and row['bb_width'] > min_bb_width
    )

    # --- SEÑAL ---
    if put_confirm >= conf_needed and ema_cross_down and price_below_trend:
        return {"direction": "put", "duration_minutes": 5}  # máximo 5 velas
    if call_confirm >= conf_needed and ema_cross_up and price_above_trend:
        return {"direction": "call", "duration_minutes": 5}

    return None
