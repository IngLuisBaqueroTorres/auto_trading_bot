import pandas as pd
import numpy as np
import json
import os
from datetime import datetime, timedelta

try:
    import talib as ta
except ImportError:
    raise ImportError("Instala: pip install ta-lib")

PARAMS_V5 = None
CONSECUTIVE_LOSSES = 0
COOLDOWN_UNTIL = None


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

    # EMAs principales
    df['ema_fast'] = ta.EMA(close, timeperiod=p.get('ema_fast_period', 9))
    df['ema_slow'] = ta.EMA(close, timeperiod=p.get('ema_slow_period', 21))
    df['ema_trend'] = ta.EMA(close, timeperiod=p.get('ema_trend_period', 200))

    # RSI
    df['rsi'] = ta.RSI(close, timeperiod=p.get('rsi_period', 13))

    # ADX (fuerza de tendencia)
    df['adx'] = ta.ADX(high, low, close, timeperiod=p.get('adx_period', 14))

    # Bandas de Bollinger
    bb_window = p.get('bb_window', 30)
    bb_std = p.get('bb_stddev', 2.0)
    upper, middle, lower = ta.BBANDS(close, timeperiod=bb_window, nbdevup=bb_std, nbdevdn=bb_std)
    df['bb_upper'] = upper
    df['bb_lower'] = lower
    df['bb_middle'] = middle
    df['bb_width'] = np.where(middle != 0, (upper - lower) / middle, 0)

    return df


def self_adjusting_strategy_v5(data: pd.DataFrame, params: dict = None,
                               last_signal: str = None, current_hour: int = None):
    """Estrategia híbrida adaptativa V5 mejorada con filtros de tendencia, momentum y cooldown."""
    global CONSECUTIVE_LOSSES, COOLDOWN_UNTIL

    if params is None:
        params = get_params_v5()

    if len(data) < 200:
        return None

    # --- COOLDOWN INTELIGENTE ---
    if COOLDOWN_UNTIL and datetime.now() < COOLDOWN_UNTIL:
        return None

    # --- HORARIO DE OPERACIÓN ---
    if current_hour is None:
        current_hour = datetime.now().hour

    start_hour = params.get("start_hour", 8)
    end_hour = params.get("end_hour", 20)
    if not (start_hour <= current_hour < end_hour):
        return None

    df = add_indicators(data.copy(), params)
    candle = df.iloc[-1]

    # --- PARÁMETROS BASE ---
    overbought = params.get('rsi_overbought', 60)
    oversold = params.get('rsi_oversold', 40)
    min_bb_width = params.get('min_bb_width', 0.0003)
    min_bb_trend = params.get('min_bb_width_trend', 0.0008)
    conf_needed = params.get('confirmations_to_enter', 1)
    lookback_rsi = 10
    lookback_cross = 3

    # --- FILTROS DE CALIDAD ---
    if pd.isna(candle['rsi']) or pd.isna(candle['ema_trend']):
        return None
    if candle['bb_width'] < min_bb_trend:
        return None

    # --- TENDENCIA PRINCIPAL (EMA 200) ---
    price_above_trend = candle['close'] > candle['ema_trend']
    price_below_trend = candle['close'] < candle['ema_trend']

    # --- CONFIRMACIÓN DE TENDENCIA ADICIONAL (EMA 10 vs 30) ---
    ema_fast2 = ta.EMA(df['close'], timeperiod=params.get('ema_fast_extra', 10))
    ema_slow2 = ta.EMA(df['close'], timeperiod=params.get('ema_slow_extra', 30))
    trend_up = ema_fast2.iloc[-1] > ema_slow2.iloc[-1]
    trend_down = ema_fast2.iloc[-1] < ema_slow2.iloc[-1]

    if params.get("require_ema_extra_alignment", True):
        if trend_up and not price_above_trend:
            return None
        if trend_down and not price_below_trend:
            return None

    # --- MOMENTUM FILTER (RSI + ADX) ---
    if params.get("require_momentum", True):
        if 45 <= candle['rsi'] <= 55:
            return None  # zona neutral
        if candle['adx'] < params.get("adx_min", 20):
            return None  # baja fuerza de tendencia

    # --- CRUCE RECIENTE DE EMA (9 vs 21) ---
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

    # --- SEÑAL FINAL ---
    if put_confirm >= conf_needed and ema_cross_down and price_below_trend:
        return {"direction": "put", "duration_minutes": 5}

    if call_confirm >= conf_needed and ema_cross_up and price_above_trend:
        return {"direction": "call", "duration_minutes": 5}

    return None


def register_trade_result(result: str):
    """Actualiza el estado del bot tras cada operación (para cooldown inteligente)."""
    global CONSECUTIVE_LOSSES, COOLDOWN_UNTIL
    params = get_params_v5()

    if result == "loss":
        CONSECUTIVE_LOSSES += 1
    else:
        CONSECUTIVE_LOSSES = 0

    if CONSECUTIVE_LOSSES >= params.get("cooldown_after_losses", 2):
        minutes = params.get("cooldown_minutes", 5)
        COOLDOWN_UNTIL = datetime.now() + timedelta(minutes=minutes)
        print(f"[COOLDOWN] Activado por {minutes} minutos tras {CONSECUTIVE_LOSSES} pérdidas consecutivas.")
