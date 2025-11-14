# main.py COMPLETO (sobrescribe el viejo)
import time
import importlib
from datetime import datetime
from iqoptionapi.stable_api import IQ_Option
from config import EMAIL
from utils.helpers import get_candle_dataframe, is_market_open
from utils.telegram_notifier import send_telegram_message
from utils.logger import setup_logger
from utils.config_manager import get_settings
from utils.strategy_selector import AVAILABLE_STRATEGIES
from utils.trade_logger import log_trade
from utils.news_fetcher import fetch_high_impact_news, is_news_time, is_relevant_for_pair

logger = setup_logger()

def connect_iq_option(email, password, max_retries=5):
    """Intenta conectar a IQ Option con reintentos y backoff progresivo."""
    logger.info(f"Intentando conectar con email: {email}")

    if not email or not password:
        logger.error("Faltan credenciales en .env. Abortando ejecución.")
        send_telegram_message("Faltan credenciales en .env. Bot detenido.")
        return None

    API = IQ_Option(email, password)

    for attempt in range(1, max_retries + 1):
        API.connect()
        if API.check_connect():
            logger.info("Conectado exitosamente a IQ Option.")
            return API
        wait_time = 5 * attempt
        logger.warning(f"Intento {attempt}/{max_retries} fallido. Reintentando en {wait_time}s...")
        time.sleep(wait_time)

    logger.error("No se pudo conectar a IQ Option tras varios intentos.")
    send_telegram_message("No se pudo conectar a IQ Option tras varios intentos. Reintentar más tarde.")
    return None

def main():
    # === Cargar configuración ===
    settings = get_settings()
    BALANCE_MODE = settings.get("BALANCE_MODE", "PRACTICE").upper()
    PAIR = settings.get("PAIR", "EURUSD")
    AMOUNT = settings.get("AMOUNT", 1.0)
    DURATION = settings.get("DURATION", 1)
    USE_PERCENT_MODE = settings.get("USE_PERCENT_MODE", False)
    MAX_RETRY_PER_SIGNAL = settings.get("MAX_RETRY_PER_SIGNAL", 1)
    SIGNAL_COOLDOWN_MINUTES = settings.get("SIGNAL_COOLDOWN_MINUTES", 1)
    SIGNAL_COOLDOWN_SECONDS = SIGNAL_COOLDOWN_MINUTES * 60

    # === STOP WIN/LOSS ===
    if USE_PERCENT_MODE:
        STOP_WIN = settings.get("TRAILING_STOP_WIN_PERCENT", 2.0)
        STOP_LOSS = settings.get("TRAILING_STOP_LOSS_PERCENT", 1.0)
    else:
        STOP_WIN = settings.get("STOP_WIN", 10.0)
        STOP_LOSS = settings.get("STOP_LOSS", 5.0)

    # === Cargar estrategia ===
    STRATEGY_NAME = settings.get("STRATEGY", "self_adjusting_strategy_v6")
    strategy_info = AVAILABLE_STRATEGIES.get(STRATEGY_NAME)
    if not strategy_info:
        logger.error(f"Estrategia '{STRATEGY_NAME}' no encontrada.")
        send_telegram_message(f"Estrategia '{STRATEGY_NAME}' no existe.")
        return

    try:
        module = importlib.import_module(strategy_info["module"])
        selected_strategy = getattr(module, strategy_info["function"])
        if not callable(selected_strategy):
            raise AttributeError("La función no es callable")
    except Exception as e:
        logger.error(f"Error al cargar estrategia: {e}")
        send_telegram_message("Error crítico al cargar estrategia.")
        return

    # === Conexión IQ Option ===
    EMAIL = settings.get("EMAIL")
    PASSWORD = settings.get("PASSWORD")
    API = connect_iq_option(EMAIL, PASSWORD)
    if API is None:
        return
    API.change_balance(BALANCE_MODE)
    initial_balance = API.get_balance()
    current_balance = initial_balance

    # === Configurar STOP ===
    if not USE_PERCENT_MODE:
        target_balance = initial_balance + STOP_WIN
        stop_balance = initial_balance - STOP_LOSS
    else:
        target_balance = initial_balance * (1 + STOP_WIN / 100)
        stop_balance = initial_balance * (1 - STOP_LOSS / 100)

    send_telegram_message(
        f"Bot iniciado en {BALANCE_MODE} | Par: {PAIR}\n"
        f"Balance inicial: ${initial_balance:.2f} | Entrada: ${AMOUNT:.2f}"
    )

    # === Variables de control ===
    last_signal = None
    last_order_time = 0
    failed_signal = None
    failed_signal_time = 0
    total_pnl = 0.0

    while True:
        if not API.check_connect():
            API = connect_iq_option(EMAIL, PASSWORD)
            if API is None:
                break
            API.change_balance(BALANCE_MODE)
            continue

        if not is_market_open(API, PAIR):
            time.sleep(600)
            continue

        candles = get_candle_dataframe(API, PAIR, 60, 30)
        if candles is None or len(candles) < 20:
            time.sleep(5)
            continue

        # --- Noticias ---
        try:
            all_news = fetch_high_impact_news()
            relevant_news = is_relevant_for_pair(all_news, PAIR)
            if is_news_time(datetime.now(), relevant_news, before=20, after=10):
                time.sleep(300)
                continue
        except:
            time.sleep(60)

        # --- Generar señal ---
        signal_res = selected_strategy(candles, last_signal, current_hour=datetime.now().hour)
        if not signal_res:
            time.sleep(5)
            continue

        direction = signal_res.get("direction")
        current_time = time.time()
        if signal_res == last_signal and (current_time - last_order_time) < 70:
            time.sleep(60)
            continue

        # --- Reintentos ---
        is_retry = False
        if failed_signal and failed_signal.get("direction") == direction and (current_time - failed_signal_time) < 120:
            retries = failed_signal.get("retries", 0)
            if retries >= MAX_RETRY_PER_SIGNAL:
                remaining = SIGNAL_COOLDOWN_SECONDS - (current_time - failed_signal_time)
                if remaining > 0:
                    time.sleep(min(remaining, 60))
                continue
            is_retry = True
        else:
            failed_signal = None

        balance = API.get_balance()
        trade_amount = AMOUNT
        if BALANCE_MODE == "REAL" and trade_amount < 1.0:
            trade_amount = 1.0

        # --- Ejecutar orden según tipo ---
        order_success = False
        order_id = None
        try:
            if "-OTC" in PAIR:
                status, order_id = API.buy(trade_amount, PAIR, direction, DURATION)
            else:
                status, order_id = API.buy_digital_spot(PAIR, trade_amount, direction, DURATION)

            if status:
                order_success = True
        except Exception as e:
            logger.error(f"Error al ejecutar orden: {e}")

        if order_success:
            last_signal = signal_res
            last_order_time = current_time
            failed_signal = None

            # --- Esperar resultado ---
            time.sleep(DURATION * 60 + 5)
            if "-OTC" in PAIR:
                profit = API.check_win_v3(order_id)
            else:
                check, profit = API.check_win_digital(order_id)

            result = "win" if profit > 0 else "loss" if profit < 0 else "draw"

            # --- Actualizar modelos ML ---
            try:
                from strategies.bot.self_adjusting_markI import markI_update_result
                from strategies.bot.self_adjusting_markII import markII_update_result
                if result in ["win", "loss"] and last_signal:
                    try: markI_update_result(candles, last_signal, result)
                    except: pass
                    if "markii" in STRATEGY_NAME.lower() or selected_strategy.__name__ == "self_adjusting_strategy_markII":
                        markII_update_result(candles, last_signal, result)
            except:
                pass

            new_balance = API.get_balance()
            total_pnl += profit
            log_trade({**signal_res, "result": result, "profit": profit, "balance": new_balance})

            current_balance = new_balance

            # --- Stop Win / Loss ---
            if not USE_PERCENT_MODE:
                if current_balance >= target_balance or current_balance <= stop_balance:
                    break
            else:
                if current_balance >= target_balance:
                    target_balance = current_balance * (1 + STOP_WIN / 100)
                    stop_balance = current_balance * (1 - STOP_LOSS / 100)
                elif current_balance <= stop_balance:
                    break

        else:
            retries = (failed_signal.get("retries", 0) if failed_signal else 0) + 1
            failed_signal = {**signal_res, "retries": retries}
            failed_signal_time = current_time
            if retries >= MAX_RETRY_PER_SIGNAL:
                time.sleep(SIGNAL_COOLDOWN_SECONDS)
            else:
                time.sleep(30)

if __name__ == "__main__":
    main()
