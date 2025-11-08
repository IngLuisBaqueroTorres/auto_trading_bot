import pandas as pd
import numpy as np
from datetime import datetime, timezone
import time
import logging

from utils.news_fetcher import fetch_high_impact_news, is_relevant_for_pair, is_news_time
from utils.telegram_notifier import send_telegram_message

logger = logging.getLogger("TradingBot")

def self_adjusting_strategy_v6(df: pd.DataFrame, last_signal=None, **kwargs):
    """
    Estrategia autoajustable híbrida v6
    - Controla pausas ante noticias
    - Usa trailing stop dinámico
    - Señales basadas en momentum + confirmación de tendencia
    """

    current_hour = kwargs.get("current_hour", datetime.now().hour)
    pair = kwargs.get("PAIR", "EURUSD")

    # === Verificación de noticias ===
    now = datetime.now(timezone.utc)
    events = fetch_high_impact_news()
    relevant_news = is_relevant_for_pair(events, pair)

    if relevant_news and is_news_time(now, relevant_news, before=30, after=15):
        next_event = relevant_news[0]
        msg = (f"📰 <b>Alta volatilidad esperada</b>\n"
               f"{next_event['title']} ({next_event['currency']}) "
               f"{next_event['time'].strftime('%H:%M UTC')}\n"
               f"⏸️ Bot en pausa temporal.")
        logger.info(msg.replace("<b>", "").replace("</b>", ""))
        send_telegram_message(msg)
        time.sleep(600)  # Pausa 10 min antes de seguir
        return None

    # === Indicadores base ===
    close = df["close"].values
    df["ema_fast"] = pd.Series(close).ewm(span=5).mean()
    df["ema_slow"] = pd.Series(close).ewm(span=20).mean()
    df["rsi"] = calc_rsi(close, 14)
    df["atr"] = calc_atr(df, 14)

    # === Señales ===
    last_row = df.iloc[-1]
    prev_row = df.iloc[-2]

    ema_cross_up = prev_row["ema_fast"] < prev_row["ema_slow"] and last_row["ema_fast"] > last_row["ema_slow"]
    ema_cross_down = prev_row["ema_fast"] > prev_row["ema_slow"] and last_row["ema_fast"] < last_row["ema_slow"]

    if ema_cross_up and last_row["rsi"] > 50:
        direction = "call"
    elif ema_cross_down and last_row["rsi"] < 50:
        direction = "put"
    else:
        return None

    return {
        "direction": direction,
        "rsi": float(last_row["rsi"]),
        "atr": float(last_row["atr"]),
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S %Z"),
        "pair": pair
    }


# === Indicadores auxiliares ===

def calc_rsi(close, period=14):
    delta = np.diff(close)
    gain = np.where(delta > 0, delta, 0)
    loss = np.where(delta < 0, -delta, 0)
    avg_gain = pd.Series(gain).rolling(window=period, min_periods=1).mean()
    avg_loss = pd.Series(loss).rolling(window=period, min_periods=1).mean()
    rs = avg_gain / (avg_loss + 1e-10)
    rsi = 100 - (100 / (1 + rs))
    rsi = np.insert(rsi, 0, 50)
    return rsi


def calc_atr(df, period=14):
    high = df["high"].values
    low = df["low"].values
    close = df["close"].values
    tr = np.maximum.reduce([
        high[1:] - low[1:],
        np.abs(high[1:] - close[:-1]),
        np.abs(low[1:] - close[:-1])
    ])
    atr = pd.Series(tr).rolling(window=period, min_periods=1).mean()
    atr = np.insert(atr, 0, atr[0])
    return atr
