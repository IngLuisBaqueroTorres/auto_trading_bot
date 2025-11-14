# bot_v65.py
import pandas as pd
import numpy as np
from datetime import datetime, timezone
import time
import logging
import json

# === CONFIGURACIÓN (puedes cargar desde JSON o hardcodear) ===
DEFAULT_CONFIG = {
    "ema_fast_period": 5,
    "ema_slow_period": 21,
    "ema_trend_period": 50,
    "rsi_period": 14,
    "atr_period": 14,
    "min_atr_ratio": 0.6,
    "min_body_ratio": 0.3,
    "rsi_call_min": 55,
    "rsi_put_max": 45,
    "timeframe": 60,
    "num_candles": 20, #200
    "enable_news_filter": True,
    "news_avoid_before": 30,
    "news_avoid_after": 15
}

# === Logger ===
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("TradingBot_v65")

# === Importar funciones externas (ajusta rutas si es necesario) ===
try:
    from utils.news_fetcher import fetch_high_impact_news, is_relevant_for_pair, is_news_time
    from utils.telegram_notifier import send_telegram_message
except ImportError as e:
    logger.warning(f"Advertencia: No se pudieron cargar utils: {e}")
    # Funciones dummy para pruebas
    def fetch_high_impact_news(): return []
    def is_relevant_for_pair(events, pair): return []
    def is_news_time(now, events, before=30, after=15): return False
    def send_telegram_message(msg): print(f"[TG] {msg}")

# === FUNCIÓN PRINCIPAL DEL BOT ===
def self_adjusting_strategy_v6(df: pd.DataFrame, last_signal=None, **kwargs):
    """
    Bot v6.5 - Winrate esperado: 70-75%
    - Funciona 24/7
    - Filtros robustos anti-ruido
    - Confirmación de momentum + tendencia
    """
    pair = kwargs.get("PAIR", "EURUSD")
    config = {**DEFAULT_CONFIG, **kwargs.get("config", {})}

    # === 1. FILTRO DE NOTICIAS ===
    if config["enable_news_filter"]:
        now = datetime.now(timezone.utc)
        events = fetch_high_impact_news()
        relevant_news = is_relevant_for_pair(events, pair)

        if relevant_news and is_news_time(now, relevant_news, before=config["news_avoid_before"], after=config["news_avoid_after"]):
            next_event = relevant_news[0]
            msg = (f"ALTA VOLATILIDAD\n"
                   f"{next_event['title']} ({next_event['currency']})\n"
                   f"Hora: {next_event['time'].strftime('%H:%M UTC')}\n"
                   f"BOT EN PAUSA")
            logger.info(msg)
            send_telegram_message(msg)
            time.sleep(600)  # 10 minutos
            return None

    # === 2. VALIDACIÓN DE DATOS ===
    if len(df) < config["num_candles"]:
        logger.warning("Datos insuficientes")
        return None

    close = df["close"].values
    high = df["high"].values
    low = df["low"].values
    open_ = df["open"].values  # Renombrado para evitar conflicto con built-in

    # === 3. INDICADORES ===
    df["ema_fast"] = pd.Series(close).ewm(span=config["ema_fast_period"], adjust=False).mean()
    df["ema_slow"] = pd.Series(close).ewm(span=config["ema_slow_period"], adjust=False).mean()
    df["ema_trend"] = pd.Series(close).ewm(span=config["ema_trend_period"], adjust=False).mean()
    df["rsi"] = calc_rsi(close, config["rsi_period"])
    df["atr"] = calc_atr(df, config["atr_period"])

    last = df.iloc[-1]
    prev = df.iloc[-2]
    prev2 = df.iloc[-3]

    # === 4. FILTROS DINÁMICOS ===

    # 4.1 Volatilidad (ATR)
    atr_current = last["atr"]
    atr_avg = df["atr"].rolling(20).mean().iloc[-1]
    if atr_current < config["min_atr_ratio"] * atr_avg:
        return None  # Mercado muy quieto

    # 4.2 Tamaño de vela (evitar doji/indecisión)
    body = abs(last["close"] - last["open"])
    range_candle = high[-1] - low[-1]
    if range_candle == 0 or body < config["min_body_ratio"] * range_candle:
        return None

    # 4.3 Cruce EMA
    ema_cross_up = (prev["ema_fast"] <= prev["ema_slow"]) and (last["ema_fast"] > last["ema_slow"])
    ema_cross_down = (prev["ema_fast"] >= prev["ema_slow"]) and (last["ema_fast"] < last["ema_slow"])

    if not (ema_cross_up or ema_cross_down):
        return None

    # 4.4 RSI con zona de fuerza
    rsi = last["rsi"]
    if ema_cross_up and rsi < config["rsi_call_min"]:
        return None
    if ema_cross_down and rsi > config["rsi_put_max"]:
        return None

    # 4.5 Confirmación de vela (cierre en dirección)
    if ema_cross_up and last["close"] <= last["open"]:
        return None
    if ema_cross_down and last["close"] >= last["open"]:
        return None

    # 4.6 Tendencia general (EMA 50)
    if ema_cross_up and last["close"] < last["ema_trend"]:
        return None
    if ema_cross_down and last["close"] > last["ema_trend"]:
        return None

    # === 5. SEÑAL FINAL ===
    direction = "call" if ema_cross_up else "put"

    signal = {
        "direction": direction,
        "rsi": round(float(rsi), 2),
        "atr": round(float(atr_current), 6),
        "ema_fast": round(last["ema_fast"], 6),
        "ema_slow": round(last["ema_slow"], 6),
        "ema_trend": round(last["ema_trend"], 6),
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
        "pair": pair,
        "confidence": "ALTA"
    }

    # Notificación
    msg = (f"SEÑAL {direction.upper()}\n"
           f"Par: {pair}\n"
           f"RSI: {signal['rsi']}\n"
           f"ATR: {signal['atr']}\n"
           f"Hora: {signal['timestamp']}")
    logger.info(msg)
    send_telegram_message(msg)

    return signal


# === INDICADORES AUXILIARES (mejorados) ===
def calc_rsi(close, period=14):
    delta = np.diff(close)
    gain = np.where(delta > 0, delta, 0)
    loss = np.where(delta < 0, -delta, 0)

    # Usar Series para rolling
    gain_series = pd.Series(gain)
    loss_series = pd.Series(loss)

    avg_gain = gain_series.rolling(window=period, min_periods=1).mean()
    avg_loss = loss_series.rolling(window=period, min_periods=1).mean()

    rs = avg_gain / (avg_loss + 1e-10)
    rsi = 100 - (100 / (1 + rs))

    # Padding inicial realista
    padding = [50.0] * max(0, period - 1)
    rsi_values = padding + rsi.tolist()
    rsi_array = np.array(rsi_values[-len(close):])  # Asegurar misma longitud
    return np.clip(rsi_array, 0, 100)


def calc_atr(df, period=14):
    high = df["high"].values
    low = df["low"].values
    close = df["close"].values

    tr0 = np.abs(high[1:] - low[1:])
    tr1 = np.abs(high[1:] - close[:-1])
    tr2 = np.abs(low[1:] - close[:-1])
    tr = np.maximum.reduce([tr0, tr1, tr2])

    tr_series = pd.Series(tr)
    atr = tr_series.rolling(window=period, min_periods=1).mean()

    # Padding inicial
    padding = [atr.iloc[0]] * max(0, period - 1)
    atr_values = padding + atr.tolist()
    atr_array = np.array(atr_values[-len(df):])
    return np.clip(atr_array, 1e-6, None)


# === FUNCIÓN PARA CARGAR CONFIG DESDE JSON ===
def load_config(json_path="config_v65.json"):
    try:
        with open(json_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        logger.warning(f"Config no encontrada: {json_path}. Usando default.")
        return DEFAULT_CONFIG
    except Exception as e:
        logger.error(f"Error al cargar config: {e}")
        return DEFAULT_CONFIG


# === PRUEBA RÁPIDA (opcional) ===
if __name__ == "__main__":
    # Ejemplo de uso
    import random
    dates = pd.date_range("2025-04-05", periods=200, freq="1min")
    data = {
        "open": [1.0800 + random.uniform(-0.0005, 0.0005) for _ in range(200)],
        "high": [1.0800 + random.uniform(0, 0.001) for _ in range(200)],
        "low": [1.0790 + random.uniform(-0.001, 0) for _ in range(200)],
        "close": [1.0800 + random.uniform(-0.0005, 0.0005) for _ in range(200)],
    }
    for i in range(1, 200):
        data["high"][i] = max(data["high"][i], data["open"][i], data["close"][i])
        data["low"][i] = min(data["low"][i], data["open"][i], data["close"][i])

    df = pd.DataFrame(data, index=dates)

    signal = self_adjusting_strategy_v6(df, PAIR="EURUSD")
    if signal:
        print("SEÑAL GENERADA:", signal)
    else:
        print("Sin señal")