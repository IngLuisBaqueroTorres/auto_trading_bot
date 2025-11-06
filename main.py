from iqoptionapi.stable_api import IQ_Option
import time
from datetime import datetime
import os
import subprocess
import sys
import importlib
from dotenv import load_dotenv

from utils.helpers import get_candle_dataframe, is_market_open
from utils.telegram_notifier import send_telegram_message
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
send_telegram_message(f"🤖 Bot iniciado con estrategia: {strategy_name}")
time.sleep(0.5)  # Anti-flood Telegram

END_HOUR = 20
REPORT_DIR = "reports"
os.makedirs(REPORT_DIR, exist_ok=True)

# --- Conexión ---
logger.info("🔌 Conectando a IQ Option...")
API = IQ_Option(EMAIL, PASSWORD)
try:
    API.connect()
except Exception as e:
    logger.error("❌ Falló la conexión inicial a IQ Option.")
    logger.error(f"   Error: {e}")
    send_telegram_message("❌ Falló la conexión a IQ Option. Verifica credenciales o red.")
    exit()

if not API.check_connect():
    logger.error("❌ No se pudo verificar la conexión.")
    send_telegram_message("❌ No se pudo conectar a IQ Option.")
    exit()

API.change_balance(settings['BALANCE_MODE'])
logger.info(f"✅ Conectado en modo {settings['BALANCE_MODE']}")
send_telegram_message(f"✅ Conectado a IQ Option en modo {settings['BALANCE_MODE']}")
time.sleep(0.5)

# ✅ Capturar saldo inicial y definir stop win/loss
initial_balance = API.get_balance()
STOP_WIN = settings.get('STOP_WIN', 10)
STOP_LOSS = settings.get('STOP_LOSS', 10)

# --- Trailing Stop ---
TRAILING_STOP_ENABLED = settings.get('TRAILING_STOP_ENABLED', False)
TRAILING_STOP_WIN_PERCENT = settings.get('TRAILING_STOP_WIN_PERCENT', 2.0)
TRAILING_STOP_LOSS_PERCENT = settings.get('TRAILING_STOP_LOSS_PERCENT', 1.0)

target_win = initial_balance + STOP_WIN
target_loss = initial_balance - STOP_LOSS

logger.info(f"💰 Saldo inicial: {initial_balance}")
logger.info(f"🎯 Stop Win: {target_win} | 🛑 Stop Loss: {target_loss}")
if TRAILING_STOP_ENABLED:
    logger.info("📈 Trailing Stop activado (modo escalera)")

send_telegram_message(
    f"💰 <b>Saldo inicial:</b> ${initial_balance:.2f}\n🎯 <b>Stop Win:</b> ${target_win:.2f}\n🛑 <b>Stop Loss:</b> ${target_loss:.2f}"
)
time.sleep(0.5)

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
        current_balance = API.get_balance()

        # ✅ Validación Stop Win / Stop Loss
        if current_balance >= target_win:
            if TRAILING_STOP_ENABLED:
                msg = f"🪜 <b>Meta alcanzada (${current_balance:.2f})</b>. Subiendo escalón."
                logger.info(msg.replace("<b>", "").replace("</b>", ""))
                send_telegram_message(msg)
                time.sleep(0.5)
                target_win += STOP_WIN
                target_loss += STOP_WIN
                logger.info(f"   Nuevo Stop Win: {target_win:.2f} | Nuevo Stop Loss: {target_loss:.2f}")
            else:
                msg = f"🏁 <b>Bot detenido: Meta alcanzada.</b>\nBalance final: ${current_balance:.2f}"
                logger.info(f"🏁 Stop Win alcanzado ({current_balance:.2f} >= {target_win:.2f}). Cerrando bot...")
                send_telegram_message(msg)
                break

        if current_balance <= target_loss:
            msg = f"🏳️ <b>Bot detenido: Stop Loss alcanzado.</b>\nBalance final: ${current_balance:.2f}"
            logger.info(f"🏳️ Stop Loss alcanzado ({current_balance:.2f} <= {target_loss:.2f}). Bot detenido.")
            send_telegram_message(msg)
            break

        if current_hour >= END_HOUR:
            msg = "🕒 Hora límite alcanzada. Cerrando bot..."
            logger.info(msg)
            send_telegram_message(msg)
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

        try:
            signal_res = selected_strategy(df, last_signal, current_hour=current_hour)
        except Exception as e:
            logger.error(f"❌ Error en la estrategia: {e}")
            signal_res = None

        if signal_res:
            direction = signal_res.get("direction")
            current_time = time.time()

            # Evitar repetición
            if signal_res == last_signal and (current_time - last_order_time) < (CANDLE_DURATION + 10):
                time.sleep(CANDLE_DURATION)
                continue

            msg = f"📊 Señal detectada en <b>{PAIR}</b>: <b>{direction.upper()}</b>"
            logger.info(f"📊 Señal detectada en {PAIR}: {direction.upper()}")
            send_telegram_message(msg)
            time.sleep(0.5)

            try:
                status, order_id = API.buy(AMOUNT, PAIR, direction, DURATION)

                if status:
                    send_telegram_message(
                        f"🚀 <b>Nueva operación abierta</b>\nPar: {PAIR}\nDirección: {direction.upper()}\nMonto: ${AMOUNT}"
                    )
                    time.sleep(0.5)
                    last_signal = signal_res
                    last_order_time = current_time
                    logger.info(f"✅ Orden ejecutada en {PAIR} | ID: {order_id}")

                    time.sleep(DURATION * 60 + 5)
                    profit = API.check_win_v3(order_id)
                    new_balance = API.get_balance()

                    if profit > 0:
                        result = "win"
                        logger.info(f"🏆 Operación GANADA en {PAIR} | Profit: +{profit:.2f}")
                        send_telegram_message(
                            f"✅ <b>Operación GANADA</b> en {PAIR}.\nProfit: +${profit:.2f}\nBalance actual: ${new_balance:.2f}"
                        )
                    elif profit < 0:
                        result = "loss"
                        logger.info(f"💀 Operación PERDIDA en {PAIR} | Pérdida: {profit:.2f}")
                        send_telegram_message(
                            f"❌ <b>Operación PERDIDA</b> en {PAIR}.\nPérdida: ${profit:.2f}\nBalance actual: ${new_balance:.2f}"
                        )
                    else:
                        result = "draw"
                        logger.warning(f"⚠️ Resultado neutro | Profit: {profit:.2f}")
                        send_telegram_message(f"⚠️ Operación neutra | {profit:.2f}")
                    time.sleep(0.5)

                    trade_log_data = {**signal_res, "result": result}
                    log_trade(trade_log_data)

                else:
                    logger.warning("❌ Falló ejecución de orden.")
                    time.sleep(0.5)

            except Exception as e:
                logger.error(f"⚠️ Error al ejecutar orden: {e}")
                time.sleep(0.5)
        else:
            time.sleep(CANDLE_DURATION)

except KeyboardInterrupt:
    logger.info("🛑 Interrupción manual.")
    send_telegram_message("🛑 Bot detenido manualmente.")

finally:
    logger.info("👋 Cerrando bot.")
    API.close()

    final_balance = API.get_balance()
    diff = final_balance - initial_balance
    result_icon = "🟢" if diff > 0 else "🔴"
    send_telegram_message(
        f"📊 <b>Resumen final</b>\nSaldo inicial: ${initial_balance:.2f}\nSaldo final: ${final_balance:.2f}\n"
        f"Resultado: {result_icon} ${abs(diff):.2f}"
    )
    time.sleep(0.5)

    send_telegram_message("👋 Bot cerrado correctamente.")
    if "bot" in strategy_name.lower():
        try:
            subprocess.run(["python", "optimize_strategy.py"], check=True, text=True, capture_output=True)
            send_telegram_message("🧠 Optimización post-sesión completada.")
        except subprocess.CalledProcessError as e:
            logger.error(f"❌ Error en optimización: {e.stderr}")
            restore_last_config()
            send_telegram_message("⚠️ Error durante optimización. Configuración restaurada.")
