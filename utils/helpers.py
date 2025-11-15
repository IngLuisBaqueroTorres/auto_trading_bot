import pandas as pd
import time
import time

from utils.logger import setup_logger
logger = setup_logger()

def get_candle_dataframe(API, pair, duration, num_candles=50):
    candles = API.get_candles(pair, duration, num_candles, time.time())
    df = pd.DataFrame(candles)
    df.rename(columns={"open": "open", "max": "high", "min": "low", "close": "close", "volume": "volume"}, inplace=True)
    df["time"] = pd.to_datetime(df["from"], unit="s")
    return df


def is_market_open(API, pair):
    """
    IQ Option: Si devuelve al menos una vela → mercado abierto.
    """
    try:
        candles = API.get_candles(pair, 60, 1, time.time())

        if candles and isinstance(candles, list):
            logger.debug("Mercado abierto (vela recibida).")
            return True
        else:
            logger.debug("Mercado cerrado (sin velas).")
            return False

    except Exception as e:
        logger.error(f"is_market_open() error: {e}")
        return False

def signal_to_direction(signal: str) -> str:
    mapping = {
        "BUY": "call",
        "SELL": "put"
    }
    return mapping.get(signal.upper(), None)
