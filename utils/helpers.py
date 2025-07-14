import pandas as pd
import time
import time

from utils.logger import setup_logger
logger = setup_logger()

def get_candle_dataframe(API, pair, duration, num_candles):
    candles = API.get_candles(pair, duration, num_candles, time.time())
    df = pd.DataFrame(candles)
    df.rename(columns={"open": "open", "max": "high", "min": "low", "close": "close", "volume": "volume"}, inplace=True)
    df["time"] = pd.to_datetime(df["from"], unit="s")
    return df

def is_market_open(API, pair):
    logger.debug("🔍 is_market_open(): verificando con candles")

    try:
        candles = API.get_candles(pair, 60, 1, time.time())
        if candles and isinstance(candles, list):
            logger.info("✅ Se obtuvo al menos una vela. Mercado abierto.")
            return True
        else:
            logger.warning("❌ No se pudieron obtener velas. Mercado cerrado.")
            return False
    except Exception as e:
        print("⚠️ Error al obtener velas:", e)
        return False

def signal_to_direction(signal: str) -> str:
    mapping = {
        "BUY": "call",
        "SELL": "put"
    }
    return mapping.get(signal.upper(), None)
