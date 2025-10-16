# main_debug.py
from iqoptionapi.stable_api import IQ_Option
import time
import pandas as pd
from datetime import datetime
import os

from config import (
    EMAIL, PASSWORD, BALANCE_MODE, PAIR,
    AMOUNT, DURATION, CANDLE_DURATION, NUM_CANDLES
)
from utils.helpers import get_candle_dataframe, is_market_open, signal_to_direction
from utils.logger import setup_logger

# ✅ MENÚ DE SELECCIÓN DE ESTRATEGIA
print("\n=== SELECCIONA LA ESTRATEGIA A USAR ===")
print("1) Estrategia OTC1")
print("2) Estrategia OTC2")
print("3) Estrategia Normal")
choice = input("Opción : ").strip()

if choice == "1":
    from strategies.bb_rsi_otc import bb_rsi_otc_trend as selected_strategy
    strategy_name = "OTC1"
elif choice == "2":
    from strategies.bb_rsi_otc_2 import bb_rsi_otc_trend as selected_strategy
    strategy_name = "OTC2"
else:
    from strategies.bb_rsi_normal_trend import bb_rsi_normal_trend as selected_strategy
    strategy_name = "Normal"

# ✅ Logger
logger = setup_logger()
logger.info(f"🚀 Iniciando bot con estrategia: {strategy_name}")

END_HOUR = 20
LOG_FILE = "logs/operaciones_debug.csv"
REPORT_DIR = "reports"

os.makedirs(REPORT_DIR, exist_ok=True)

# --- Conexión ---
logger.info("🔌 Conectando a IQ Option...")
API = IQ_Option(EMAIL, PASSWORD)
API.connect()
if not API.check_connect():
    logger.error("❌ No se pudo conectar a IQ Option.")
    exit()
API.change_balance(BALANCE_MODE)
logger.info(f"✅ Conectado en modo {BALANCE_MODE}")

# ✅ Capturar saldo inicial y definir stop win/loss
initial_balance = API.get_balance()
STOP_WIN = 1   # en dólares
STOP_LOSS = 10  # en dólares

target_win = initial_balance + STOP_WIN
target_loss = initial_balance - STOP_LOSS

logger.info(f"💰 Saldo inicial: {initial_balance}")
logger.info(f"🎯 Stop Win en: {target_win}")
logger.info(f"🛑 Stop Loss en: {target_loss}")

last_signal = None
last_order_time = 0

try:
    while True:
        now = datetime.now()
        current_hour = now.hour

        # ✅ Validación de stop win/stop loss
        current_balance = API.get_balance()
        if current_balance >= target_win:
            logger.info(f"🏁 Stop Win alcanzado ({current_balance} >= {target_win}). Cerrando bot...")
            break
        if current_balance <= target_loss:
            logger.info(f"🏳️ Stop Loss alcanzado ({current_balance} <= {target_loss}). Cerrando bot...")
            break

        if current_hour >= END_HOUR:
            logger.info("🕒 Hora límite alcanzada. Cerrando bot...")
            break

        if not is_market_open(API, PAIR):
            logger.warning(f"⚠️ Mercado cerrado para {PAIR}. Reintentando en 60s...")
            time.sleep(60)
            continue

        df = get_candle_dataframe(API, PAIR, CANDLE_DURATION, NUM_CANDLES)
        if df is None or df.empty:
            logger.warning("⚠️ No se recibieron datos de velas. Reintentando en 30s...")
            time.sleep(30)
            continue

        df = df.copy()

        # ✅ Evaluar estrategia seleccionada
        try:
            signal_res = selected_strategy(df, last_signal, current_hour=current_hour)
        except Exception as e:
            logger.error(f"❌ Error en la estrategia: {e}")
            signal_res = None

        if signal_res:
            direction = signal_to_direction(signal_res)
            current_time = time.time()

            # Evitar spam de entradas repetidas
            if signal_res == last_signal and (current_time - last_order_time) < (CANDLE_DURATION + 10):
                logger.debug("🚫 Señal repetida recientemente. Esperando siguiente vela...")
                time.sleep(CANDLE_DURATION)
                continue

            logger.info(f"📊 Señal detectada: {signal_res} → Ejecutando {direction.upper()}")

            try:
                direction_api = "call" if direction.upper() == "BUY" else "put"
                status, order_id = API.buy(AMOUNT, PAIR, direction.upper(), DURATION)

                if status:
                    last_signal = signal_res
                    last_order_time = current_time
                    logger.info(f"✅ Orden ejecutada | ID: {order_id}")
                    time.sleep(DURATION * 60 + 5)

                    profit = API.check_win_v3(order_id)
                    if profit > 0:
                        logger.info(f"🏆 Operación GANADA | Profit: +{profit:.2f}")
                    elif profit < 0:
                        logger.info(f"💀 Operación PERDIDA | Pérdida: {profit:.2f}")
                    else:
                        logger.warning(f"⚠️ Resultado neutro | Profit: {profit:.2f}")
                else:
                    logger.warning("❌ Falló la ejecución de la orden incluso después del intento doble")

            except Exception as e:
                logger.error(f"⚠️ Error al ejecutar orden: {e}")
        else:
            logger.debug("🔍 No se generó señal en esta vela")

        time.sleep(CANDLE_DURATION)

except KeyboardInterrupt:
    logger.info("🛑 Interrupción manual.")

finally:
    logger.info("👋 Cerrando bot.")
    API.close()
