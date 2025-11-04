# strategies/bot/self_adjusting_v5.py
import pandas as pd
import numpy as np

try:
    import talib as ta
except ImportError:
    raise ImportError("Instala: pip install ta-lib")

def add_indicators(df: pd.DataFrame, params: dict) -> pd.DataFrame:
    close = df['close'].values
    high = df['high'].values
    low = df['low'].values

    p = params

    df['ema_fast'] = ta.EMA(close, timeperiod=p.get('ema_fast_period', 9))
    df['ema_slow'] = ta.EMA(close, timeperiod=p.get('ema_slow_period', 21))
    df['rsi'] = ta.RSI(close, timeperiod=p.get('rsi_period', 13))

    bb_window = p.get('bb_window', 30)
    bb_std = p.get('bb_stddev', 2.0)
    upper, middle, lower = ta.BBANDS(close, timeperiod=bb_window, nbdevup=bb_std, nbdevdn=bb_std)
    df['bb_upper'] = upper
    df['bb_lower'] = lower
    df['bb_middle'] = middle
    df['bb_width'] = np.where(middle != 0, (upper - lower) / middle, 0)

    return df


def self_adjusting_strategy_v5(data: pd.DataFrame, params: dict):
    if len(data) < 100:
        return None

    df = data.copy()
    df = add_indicators(df, params)
    candle = df.iloc[-1]

    # --- PARÁMETROS ---
    overbought = params.get('rsi_overbought', 60)
    oversold = params.get('rsi_oversold', 40)
    min_bb = params.get('min_bb_width', 0.0003)
    conf_needed = params.get('confirmations_to_enter', 1)  # BAJADO A 1
    lookback_rsi = 10
    lookback_ema_cross = 3  # Cruce en últimas 3 velas

    # --- DEBUG ---
    if len(data) % 100 == 0:
        print(f"\n[DEBUG] Vela {len(data)} | RSI: {candle['rsi']:.2f} | BB_W: {candle['bb_width']:.6f}")

    if pd.isna(candle['rsi']) or candle['bb_width'] <= min_bb:
        return None

    # --- 1. CRUCE RECIENTE DE EMA ---
    recent = df.tail(lookback_ema_cross)
    ema_cross_up = False
    ema_cross_down = False

    for i in range(1, len(recent)):
        prev = recent.iloc[i-1]
        curr = recent.iloc[i]
        if prev['ema_fast'] <= prev['ema_slow'] and curr['ema_fast'] > curr['ema_slow']:
            ema_cross_up = True
        if prev['ema_fast'] >= prev['ema_slow'] and curr['ema_fast'] < curr['ema_slow']:
            ema_cross_down = True

    # --- 2. CONFIRMACIONES RSI EN VENTANA ---
    recent_rsi = df.tail(lookback_rsi)
    put_confirm = sum(1 for _, row in recent_rsi.iterrows() 
                     if row['rsi'] > overbought and row['bb_width'] > min_bb)
    call_confirm = sum(1 for _, row in recent_rsi.iterrows() 
                      if row['rsi'] < oversold and row['bb_width'] > min_bb)

    # --- 3. SEÑAL ---
    if put_confirm >= conf_needed and ema_cross_down:
        print(f"SEÑAL PUT! RSI={candle['rsi']:.2f} | Conf={put_confirm}")
        return {"direction": "put", "duration_minutes": 1}
    if call_confirm >= conf_needed and ema_cross_up:
        print(f"SEÑAL CALL! RSI={candle['rsi']:.2f} | Conf={call_confirm}")
        return {"direction": "call", "duration_minutes": 1}

    return None