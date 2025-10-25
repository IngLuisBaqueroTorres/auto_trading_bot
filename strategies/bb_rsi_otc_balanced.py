# strategies/bb_rsi_otc_balanced_v2_focus.py
from typing import Optional, Dict, Any
import pandas as pd
import datetime
from utils.indicators import (
    calculate_rsi,
    calculate_bollinger_bands,
    calculate_ema,
    calculate_atr
)
from utils.logger import setup_logger

logger = setup_logger()

# ----------------- PARÁMETROS AJUSTADOS -----------------
MIN_BB_WIDTH = 0.0015        # evita operar en baja volatilidad
ATR_VOLATILITY_DROP = 0.6    # si el ATR actual es < 60% del promedio, no operar
CONFIRMATIONS_TO_ENTER = 2   # número mínimo de confirmaciones
RSI_OVERBOUGHT = 70
RSI_OVERSOLD = 30
BB_TOUCH_TOLERANCE = 0.0001
EMA_PERIOD = 200
TRADING_START_HOUR = 9
TRADING_END_HOUR = 11 # 11
DYNAMIC_EXTENSION_MINUTES = 30  # extensión si hay volatilidad viva
MIN_DYNAMIC_BB_WIDTH = 0.002    # umbral para extender horario

# ---------------------------------------------------------

def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """
    Añade los indicadores necesarios para la estrategia OTC Balanced.
    """
    df = df.copy()
    if 'rsi' not in df.columns:
        df['rsi'] = calculate_rsi(df['close'], window=14)
    if 'bb_upper' not in df.columns:
        bb = calculate_bollinger_bands(df['close'], period=20, num_std_dev=2)
        df = pd.concat([df, bb], axis=1)
    if 'ema' not in df.columns:
        df['ema'] = calculate_ema(df['close'], EMA_PERIOD)
    if 'atr' not in df.columns:
        df['atr'] = calculate_atr(df, period=14)
    
    df['bb_width'] = (df['bb_upper'] - df['bb_lower']) / (df['close'] + 1e-12)
    return df

def strategy_bb_rsi_otc_balanced_v2_focus(
    df: pd.DataFrame,
    last_signal: Optional[str] = None,
    current_hour: Optional[int] = None
) -> Optional[Dict[str, Any]]:
    """
    Estrategia BB + RSI + EMA optimizada para OTC.
    - Opera principalmente entre 9:00 y 11:00
    - Se extiende hasta 11:30 si hay buena volatilidad
    - Incluye control de ATR y amplitud de bandas
    """
    df = add_indicators(df).dropna()
    if len(df) < EMA_PERIOD:
        return None


    # Última y penúltima vela
    last = df.iloc[-1]
    prev = df.iloc[-2]

    # -------- Control horario (interno o externo) --------
    now = datetime.datetime.now()
    if current_hour is None:
        current_hour = now.hour
        current_minute = now.minute
    else:
        current_minute = now.minute

    # -------- HORARIO DINÁMICO --------
    in_main_window = TRADING_START_HOUR <= current_hour < TRADING_END_HOUR
    in_dynamic_window = (
        (current_hour == TRADING_END_HOUR and current_minute <= DYNAMIC_EXTENSION_MINUTES)
        and last['bb_width'] > MIN_DYNAMIC_BB_WIDTH
    )

    if not (in_main_window or in_dynamic_window):
        logger.debug(f"⏰ Fuera de horario operativo OTC ({current_hour}:{current_minute:02d})")
        return None

    # -------- FILTROS DE VOLATILIDAD --------
    avg_atr = df['atr'].tail(20).mean()
    bb_width = last['bb_width']

    if bb_width < MIN_BB_WIDTH:
        logger.debug(f"⚠️ Volatilidad insuficiente (BB width={bb_width:.6f})")
        return None

    if last['atr'] < avg_atr * ATR_VOLATILITY_DROP:
        logger.debug(f"⚠️ ATR bajo ({last['atr']:.6f} < {avg_atr*ATR_VOLATILITY_DROP:.6f}), mercado plano")
        return None

    # -------- LÓGICA PRINCIPAL --------
    confirmations = 0
    direction = None

    # Reversión bajista (PUT)
    if (
        prev['close'] > prev['bb_upper'] - BB_TOUCH_TOLERANCE and
        last['close'] < last['bb_upper'] - BB_TOUCH_TOLERANCE and
        last['rsi'] > RSI_OVERBOUGHT and
        last['close'] < last['ema']
    ):
        confirmations += 1
        direction = "put"

    # Reversión alcista (CALL)
    if (
        prev['close'] < prev['bb_lower'] + BB_TOUCH_TOLERANCE and
        last['close'] > last['bb_lower'] + BB_TOUCH_TOLERANCE and
        last['rsi'] < RSI_OVERSOLD and
        last['close'] > last['ema']
    ):
        confirmations += 1
        direction = "call"

    if confirmations < CONFIRMATIONS_TO_ENTER or direction is None:
        return None

    logger.info(
        f"✅ Señal OTC detectada: {direction.upper()} | RSI={last['rsi']:.2f} | BB width={bb_width:.4f} | ATR={last['atr']:.5f}"
    )

    return {
        "direction": direction,
        "rsi": last['rsi'],
        "bb_width": bb_width,
        "ema": last['ema'],
        "atr": last['atr'],
        "timestamp": now
    }
