import pandas as pd
import numpy as np
from datetime import datetime
import time

from utils.telegram_notifier import send_telegram_message
from utils.logger import setup_logger

logger = setup_logger()

# --- Configuración dinámica ---
MAX_RETRIES = 2           # cantidad máxima de intentos antes del cooldown
COOLDOWN_MINUTES = 5      # minutos de pausa después de fallar repetidamente

# Variables de estado
retry_counter = 0
cooldown_until = None


# --- Indicadores ---
def add_indicators(df: pd.DataFrame, params: dict) -> pd.DataFrame:
    close = df['close'].values
    high = df['high'].values
    low = df['low'].values

    df['ema_fast'] = pd.Series(close).ewm(span=params['ema_fast'], min_periods=1).mean()
    df['ema_slow'] = pd.Series(close).ewm(span=params['ema_slow'], min_periods=1).mean()
    df['rsi'] = compute_rsi(close, params['rsi_period'])
    df['atr'] = compute_atr(high, low, close, params['atr_period'])
    return df


def compute_rsi(prices, period=14):
    delta = np.diff(prices)
    gain = np.maximum(delta, 0)
    loss = -np.minimum(delta, 0)
    avg_gain = pd.Series(gain).rolling(window=period, min_periods=1).mean()
    avg_loss = pd.Series(loss).rolling(window=period, min_periods=1).mean()
    rs = avg_gain / (avg_loss + 1e-10)
    rsi = 100 - (100 / (1 + rs))
    return np.concatenate([[50], rsi])  # rellena primer valor para igualar tamaño


def compute_atr(high, low, close, period=14):
    tr = np.maximum(high[1:] - low[1:], np.maximum(abs(high[1:] - close[:-1]), abs(low[1:] - close[:-1])))
    atr = pd.Series(tr).rolling(window=period, min_periods=1).mean()
    atr = np.insert(atr.values, 0, 0)
    return atr


# --- Señal principal ---
def should_enter_trade(df: pd.DataFrame, params: dict) -> str:
    last = df.iloc[-1]
    prev = df.iloc[-2]

    if last['ema_fast'] > last['ema_slow'] and prev['ema_fast'] <= prev['ema_slow'] and last['rsi'] < 70:
        return "call"
    elif last['ema_fast'] < last['ema_slow'] and prev['ema_fast'] >= prev['ema_slow'] and last['rsi'] > 30:
        return "put"
    return None


# --- Estrategia estándar compatible con main ---
def self_adjusting_strategy_v5(df, last_signal=None, current_hour=None):
    """
    Estrategia BOT v5 (Híbrido Adaptativo).
    Recibe el DataFrame de velas desde main.py
    y devuelve una señal si hay entrada.
    """

    global retry_counter, cooldown_until

    params = {
        "ema_fast": 5,
        "ema_slow": 15,
        "rsi_period": 14,
        "atr_period": 14,
        "timeframe": 60,
        "num_candles": 200
    }

    now = datetime.now()

    # Verifica cooldown
    if cooldown_until and now < cooldown_until:
        logger.info(f"⏸ En cooldown hasta {cooldown_until.strftime('%H:%M:%S')}")
        return None

    try:
        df = add_indicators(df, params)
        signal = should_enter_trade(df, params)

        if signal:
            logger.info(f"📈 Señal detectada: {signal.upper()}")
            send_telegram_message(f"📈 Señal detectada: {signal.upper()}")
            retry_counter = 0
            return {"direction": signal}
        else:
            logger.info("Sin señal detectada.")
            return None

    except Exception as e:
        retry_counter += 1
        logger.error(f"Error en self_adjusting_strategy_v5: {e} (Intento {retry_counter}/{MAX_RETRIES})")

        if retry_counter < MAX_RETRIES:
            send_telegram_message(f"⚠️ Error al analizar mercado: {e}")

        if retry_counter >= MAX_RETRIES:
            cooldown_until = now + pd.Timedelta(minutes=COOLDOWN_MINUTES)
            send_telegram_message(f"😴 Falló {MAX_RETRIES} veces seguidas. Descansando {COOLDOWN_MINUTES} min...")
            logger.warning(f"Entrando en cooldown hasta {cooldown_until.strftime('%H:%M:%S')}")
            retry_counter = 0

        return None
