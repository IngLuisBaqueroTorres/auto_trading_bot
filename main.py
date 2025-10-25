from iqoptionapi.stable_api import IQ_Option
import time
from datetime import datetime
import os
import subprocess
import sys
import importlib
from dotenv import load_dotenv

from utils.helpers import get_candle_dataframe, is_market_open, signal_to_direction
from utils.logger import setup_logger
from utils.config_manager import get_settings, restore_last_config
from utils.strategy_selector import AVAILABLE_STRATEGIES
from utils.trade_logger import log_trade

# --- Cargar configuración ---
load_dotenv()
settings = get_settings()
EMAIL = os.getenv("EMAIL")
PASSWORD = os.getenv("PASSWORD")

if len(sys.argv) < 2:
    print("Error: Debes proporcionar la clave de la estrategia a ejecutar.")
    print("Uso: python main.py <strategy_key>")
    exit()

strategy_key = sys.argv[1]
strategy_info = AVAILABLE_STRATEGIES.get(strategy_key)
module = importlib.import_module(strategy_info["module"])
selected_strategy = getattr(module, strategy_info["function"])
strategy_name = strategy_info["name"]

# ✅ Logger
logger = setup_logger()
logger.info(f"🚀 Iniciando bot con estrategia: {strategy_name}")

END_HOUR = 20
REPORT_DIR = "reports"

os.makedirs(REPORT_DIR, exist_ok=True)

# --- Conexión ---
logger.info("🔌 Conectando a IQ Option...")
API = IQ_Option(EMAIL, PASSWORD)
try:
    API.connect()
except Exception as e:
    logger.error(f"❌ Falló la conexión inicial a IQ Option. Causa probable: Problema de red o credenciales incorrectas.")
    logger.error(f"   Error original: {e}")
    exit()

if not API.check_connect():
    logger.error("❌ No se pudo verificar la conexión a IQ Option. Revisa tus credenciales y conexión a internet.")
    exit()
API.change_balance(settings['BALANCE_MODE'])
logger.info(f"✅ Conectado en modo {settings['BALANCE_MODE']}")

# ✅ Capturar saldo inicial y definir stop win/loss
initial_balance = API.get_balance()
STOP_WIN = settings.get('STOP_WIN', 10)
STOP_LOSS = settings.get('STOP_LOSS', 10)
target_win = initial_balance + STOP_WIN
target_loss = initial_balance - STOP_LOSS

logger.info(f"💰 Saldo inicial: {initial_balance}")
logger.info(f"🎯 Stop Win en: {target_win}")
logger.info(f"🛑 Stop Loss en: {target_loss}")

last_signal = None

# Extraer variables de settings
PAIR = settings.get('PAIR')
AMOUNT = settings.get('AMOUNT')
DURATION = settings.get('DURATION')
CANDLE_DURATION = settings.get('CANDLE_DURATION')
NUM_CANDLES = settings.get('NUM_CANDLES')
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

        df = get_candle_dataframe(API, PAIR, CANDLE_DURATION, NUM_CANDLES) # Usa variables de settings
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
            direction = signal_res.get("direction")
            current_time = time.time()

            # Evitar spam de entradas repetidas
            if signal_res == last_signal and (current_time - last_order_time) < (CANDLE_DURATION + 10):
                logger.debug("🚫 Señal repetida recientemente. Esperando siguiente vela...")
                time.sleep(CANDLE_DURATION)
                continue

            logger.info(f"📊 Señal detectada: {direction.upper()}")

            try:
                status, order_id = API.buy(AMOUNT, PAIR, direction, DURATION)

                if status:
                    last_signal = signal_res
                    last_order_time = current_time
                    logger.info(f"✅ Orden ejecutada | ID: {order_id}")
                    time.sleep(DURATION * 60 + 5)

                    profit = API.check_win_v3(order_id)
                    if profit > 0:
                        result = "win"
                        logger.info(f"🏆 Operación GANADA | Profit: +{profit:.2f}")
                    elif profit < 0:
                        result = "loss"
                        logger.info(f"💀 Operación PERDIDA | Pérdida: {profit:.2f}")
                    else:
                        result = "draw"
                        logger.warning(f"⚠️ Resultado neutro | Profit: {profit:.2f}")
                    
                    # Loguear el resultado de la operación
                    trade_log_data = {**signal_res, "result": result}
                    log_trade(trade_log_data)
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
    # Solo ejecutar el optimizador si la estrategia es la auto-ajustable
    if "bot" in strategy_name.lower():
        logger.info("🧠 Ejecutando optimización post-sesión...")
        try:
            # check=True hace que lance una excepción si el script termina con error
            subprocess.run(["python", "optimize_strategy.py"], check=True, text=True, capture_output=True)
        except subprocess.CalledProcessError as e:
            logger.error(f"❌ Error durante la optimización: {e.stderr}. Restaurando última configuración estable.")
            restore_last_config()
    else:
        logger.info("Estrategia no auto-ajustable. Omitiendo optimización.")
