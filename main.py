from iqoptionapi.stable_api import IQ_Option
import time
import pandas as pd

from config import EMAIL, PASSWORD, BALANCE_MODE, PAIR, AMOUNT, DURATION, CANDLE_DURATION, NUM_CANDLES
from strategies.wednesday import wednesday_strategy
from utils.helpers import get_candle_dataframe, is_market_open, signal_to_direction

from utils.logger import setup_logger
logger = setup_logger()

API = IQ_Option(EMAIL, PASSWORD)
API.connect()

if not API.check_connect():
    logger.error("❌ Error de conexión")
    exit()

API.change_balance(BALANCE_MODE)
logger.info(f"✅ Conectado en modo {BALANCE_MODE}")

while True:
    if not is_market_open(API, PAIR):
        logger.warning(f"⚠️ Mercado cerrado para {PAIR}")
        time.sleep(60)
        continue

    df = get_candle_dataframe(API, PAIR, CANDLE_DURATION, NUM_CANDLES)
    signal = wednesday_strategy(df)

    if signal:
        direction = signal_to_direction(signal)
        logger.info(f"📊 Señal: {signal} → Ejecutando {direction.upper()}")

        status, order_id = API.buy(AMOUNT, PAIR, direction, DURATION)
        if status:
            logger.info(f"✅ Orden ejecutada: ID {order_id}")
        else:
            logger.warning("❌ Falló al colocar la orden")

        time.sleep(65)  # Espera a la próxima vela
    else:
        logger.debug("🔍 Sin señal, esperando siguiente análisis...")
        time.sleep(60)
