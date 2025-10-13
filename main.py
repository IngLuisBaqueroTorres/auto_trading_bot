from iqoptionapi.stable_api import IQ_Option
import time
import pandas as pd
from datetime import datetime
import os
import subprocess

from config import (
    EMAIL, PASSWORD, BALANCE_MODE, PAIR,
    AMOUNT, DURATION, CANDLE_DURATION, NUM_CANDLES
)
from strategies.bb_rsi_otc import bb_rsi_otc 
from strategies.bb_rsi_strategy import add_indicators
from utils.helpers import get_candle_dataframe, is_market_open, signal_to_direction
from utils.logger import setup_logger

logger = setup_logger()

# --- Configuración general ---
END_HOUR = 20  # Hora local en la que se detiene el bot
LOG_FILE = "logs/operaciones.csv"
REPORT_DIR = "reports"

if not os.path.exists(REPORT_DIR):
    os.makedirs(REPORT_DIR)

# --- Conexión inicial ---
logger.info("🔌 Conectando a IQ Option...")
API = IQ_Option(EMAIL, PASSWORD)
API.connect()

if not API.check_connect():
    logger.error("❌ Error: No se pudo conectar a IQ Option. Verifica credenciales o conexión.")
    exit()

API.change_balance(BALANCE_MODE)
logger.info(f"✅ Conectado correctamente en modo {BALANCE_MODE}")

# --- Variables internas ---
last_signal = None
last_order_time = 0

# --- Loop principal ---
try:
    while True:
        now = datetime.now()
        current_hour = now.hour

        # 1️⃣ Cierre automático
        if current_hour >= END_HOUR:
            logger.info("🕒 Hora límite alcanzada. Cerrando sesión de trading...")
            break

        # 2️⃣ Verificar si el mercado está abierto
        if not is_market_open(API, PAIR):
            logger.warning(f"⚠️ Mercado cerrado para {PAIR}. Reintentando en 60s...")
            time.sleep(60)
            continue

        # 3️⃣ Obtener velas recientes
        df = get_candle_dataframe(API, PAIR, CANDLE_DURATION, NUM_CANDLES)
        if df is None or df.empty:
            logger.warning("⚠️ No se recibieron datos de velas. Reintentando...")
            time.sleep(30)
            continue

        # 4️⃣ Calcular indicadores
        df_with_indicators = add_indicators(df.copy()).dropna()

        # 5️⃣ Aplicar estrategia
        signal = bb_rsi_otc(df_with_indicators, last_signal)

        # 6️⃣ Ejecución de señal
        if signal:
            direction = signal_to_direction(signal)
            current_time = time.time()

            # Evitar reentrada inmediata
            if signal == last_signal and (current_time - last_order_time) < (CANDLE_DURATION + 10):
                logger.debug("🚫 Señal repetida recientemente. Esperando siguiente vela...")
                time.sleep(CANDLE_DURATION)
                continue

            logger.info(f"📊 Señal detectada: {signal} → Ejecutando {direction.upper()}")

            status, order_id = API.buy(AMOUNT, PAIR, direction, DURATION)
            if status:
                logger.info(f"✅ Orden ejecutada correctamente | ID: {order_id}")
                last_signal = signal
                last_order_time = current_time
            
                # Esperar al cierre de la operación antes de evaluar el resultado
                time.sleep(DURATION * 60 + 5)
            
                # Consultar el resultado de la operación
                try:
                    profit = API.check_win_v3(order_id)

                    if profit > 0:
                        logger.info(f"🏆 Operación GANADA | Profit: +{profit:.2f}")
                    elif profit < 0:
                        logger.info(f"💀 Operación PERDIDA | Pérdida: {profit:.2f}")
                    else:
                        logger.warning(f"⚠️ Resultado neutro | Profit: {profit:.2f}")
                except Exception as e:
                    logger.error(f"⚠️ Error al consultar resultado de operación: {e}")
            
            else:
                logger.warning("❌ Falló la ejecución de la orden en IQ Option")
            
            time.sleep(CANDLE_DURATION + 5)

        else:
            logger.debug("🔍 Sin señal clara. Esperando la próxima actualización...")
            time.sleep(CANDLE_DURATION)

except KeyboardInterrupt:
    logger.info("🛑 Interrupción manual. Cerrando bot...")

except Exception as e:
    logger.error(f"⚠️ Error inesperado: {e}")

finally:
    logger.info("📊 Ejecutando análisis de resultados diarios...")

    try:
        # Ejecuta el analizador directamente
        subprocess.run(["python", "analyze_results.py"], check=True)

        # Copia el resumen diario a /reports
        date_str = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        if os.path.exists(LOG_FILE):
            report_path = os.path.join(REPORT_DIR, f"resumen_{date_str}.csv")
            os.rename(LOG_FILE, report_path)
            logger.info(f"✅ Reporte del día guardado en: {report_path}")
        else:
            logger.warning("⚠️ No se encontró archivo de operaciones para generar reporte.")
    except Exception as e:
        logger.error(f"❌ Error al generar análisis diario: {e}")

    API.close()
    logger.info("👋 Bot finalizado correctamente.")
