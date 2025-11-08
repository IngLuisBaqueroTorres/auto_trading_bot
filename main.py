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
    STOP_WIN = settings.get("STOP_WIN", 20.0)
    STOP_LOSS = settings.get("STOP_LOSS", 10.0)
    USE_PERCENT_MODE = settings.get("USE_PERCENT_MODE", True)
    TRAILING_STOP_ENABLED = settings.get("TRAILING_STOP_ENABLED", False)
    TRAILING_STOP_WIN_PERCENT = settings.get("TRAILING_STOP_WIN_PERCENT", 2.0)
    TRAILING_STOP_LOSS_PERCENT = settings.get("TRAILING_STOP_LOSS_PERCENT", 5.0)

    # === CONTROL DE REINTENTOS Y COOLDOWN ===
    MAX_RETRY_PER_SIGNAL = settings.get("MAX_RETRY_PER_SIGNAL", 1)
    SIGNAL_COOLDOWN_MINUTES = settings.get("SIGNAL_COOLDOWN_MINUTES", 5)
    SIGNAL_COOLDOWN_SECONDS = SIGNAL_COOLDOWN_MINUTES * 60

    # === CARGAR ESTRATEGIA DINÁMICAMENTE ===
    STRATEGY_NAME = settings.get("STRATEGY", "self_adjusting_strategy_v6")
    logger.info(f"Solicitando estrategia: {STRATEGY_NAME}")

    strategy_info = AVAILABLE_STRATEGIES.get(STRATEGY_NAME)
    if not strategy_info:
        logger.error(
            f"Estrategia '{STRATEGY_NAME}' no encontrada. "
            f"Opciones válidas: {list(AVAILABLE_STRATEGIES.keys())}"
        )
        send_telegram_message(f"Estrategia '{STRATEGY_NAME}' no existe.")
        return

    try:
        module = importlib.import_module(strategy_info["module"])
        selected_strategy = getattr(module, strategy_info["function"])

        if not callable(selected_strategy):
            raise AttributeError("La función no es callable")

        logger.info(f"Estrategia cargada: {strategy_info['name']}")
        logger.info(f"Función: {selected_strategy.__name__}")

    except ImportError as e:
        logger.error(f"No se pudo importar el módulo {strategy_info['module']}: {e}")
        send_telegram_message(f"Módulo no encontrado: {strategy_info['module']}")
        return
    except AttributeError as e:
        logger.error(
            f"Función '{strategy_info['function']}' no encontrada en {strategy_info['module']}"
        )
        send_telegram_message(f"Función no encontrada: {strategy_info['function']}")
        return
    except Exception as e:
        logger.error(f"Error inesperado al cargar estrategia: {e}")
        send_telegram_message("Error crítico al cargar estrategia.")
        return

    # === Conexión con IQ Option ===
    EMAIL = settings.get("EMAIL")
    PASSWORD = settings.get("PASSWORD")

    API = connect_iq_option(EMAIL, PASSWORD)
    if API is None:
        return

    API.change_balance(BALANCE_MODE)
    balance = API.get_balance()

    # --- Meta y Stop iniciales (solo para el primer mensaje) ---
    target_balance = balance * (1 + STOP_WIN / 100)
    stop_balance = balance * (1 - STOP_LOSS / 100)

    logger.info(f"Modo: {BALANCE_MODE}")
    logger.info(f"Balance actual: ${balance:.2f}")
    logger.info(f"Meta: ${target_balance:.2f} | Stop: ${stop_balance:.2f}")

    # Mensaje de arranque con información de entrada
    entry_text = f"{AMOUNT:.2f}%" if USE_PERCENT_MODE else f"${AMOUNT}"
    send_telegram_message(
        f"Bot iniciado en modo {BALANCE_MODE}\n"
        f"Balance: ${balance:.2f}\n"
        f"Meta: ${target_balance:.2f}\n"
        f"Stop: ${stop_balance:.2f}\n"
        f"Entrada: {entry_text}"
    )

    # === VARIABLES DE CONTROL ===
    last_signal = None
    last_order_time = 0
    current_balance = balance
    failed_signal = None
    failed_signal_time = 0

    while True:
        # ---- Reconexión automática ----
        if not API.check_connect():
            logger.warning("Conexión perdida con IQ Option. Reintentando...")
            send_telegram_message("Conexión perdida. Reintentando reconexión...")
            API = connect_iq_option(EMAIL, PASSWORD)
            if API is None:
                logger.error("No se logró reconectar. Deteniendo bot.")
                send_telegram_message("No se logró reconectar. Bot detenido.")
                break
            API.change_balance(BALANCE_MODE)
            continue

        # ---- Mercado cerrado ----
        if not is_market_open(API, PAIR):
            logger.warning(f"Mercado cerrado para {PAIR}. Esperando...")
            send_telegram_message(f"Mercado cerrado para {PAIR}. Esperando apertura...")
            time.sleep(600)
            continue

        # ---- Obtener velas ----
        candles = get_candle_dataframe(API, PAIR, 60, 100)
        if candles is None or len(candles) < 50:
            time.sleep(5)
            continue

        # ---- Generar señal ----
        signal_res = selected_strategy(
            candles, last_signal, current_hour=datetime.now().hour
        )

        if signal_res:
            direction = signal_res.get("direction")
            current_time = time.time()

            # Evitar repetición rápida de la misma señal
            if signal_res == last_signal and (current_time - last_order_time) < 70:
                time.sleep(60)
                continue

            # ---- Reintento controlado por fallo previo ----
            is_retry = False
            if (
                failed_signal
                and failed_signal.get("direction") == direction
                and (current_time - failed_signal_time) < 120
            ):
                retries = failed_signal.get("retries", 0)
                if retries >= MAX_RETRY_PER_SIGNAL:
                    remaining = SIGNAL_COOLDOWN_SECONDS - (current_time - failed_signal_time)
                    if remaining > 0:
                        logger.info(f"En cooldown por fallo previo: {int(remaining)}s restantes.")
                        time.sleep(min(remaining, 60))
                    continue
                is_retry = True
            else:
                failed_signal = None

            # ---- Calcular monto de la operación ----
            balance = API.get_balance()
            trade_amount = balance * (AMOUNT / 100) if USE_PERCENT_MODE else AMOUNT

            retry_text = " (reintento)" if is_retry else ""
            msg = f"Señal{retry_text} en <b>{PAIR}</b>: <b>{direction.upper()}</b>"
            logger.info(msg)
            send_telegram_message(msg)

            order_success = False
            order_id = None

            try:
                status, order_id = API.buy(trade_amount, PAIR, direction, DURATION)
                if status:
                    order_success = True
                    logger.info(
                        f"Orden ejecutada: {PAIR} {direction.upper()} ${trade_amount:.2f}"
                    )
                    send_telegram_message(
                        f"Operación abierta: {PAIR} {direction.upper()} ${trade_amount:.2f}"
                    )
                else:
                    logger.warning(f"API.buy falló: status={status}, id={order_id}")
            except Exception as e:
                logger.error(f"Error al ejecutar orden: {e}")

            # ==== ÉXITO DE LA OPERACIÓN ====
            if order_success:
                last_signal = signal_res
                last_order_time = current_time
                failed_signal = None

                # Esperar cierre
                time.sleep(DURATION * 60 + 5)
                profit = API.check_win_v3(order_id)
                new_balance = API.get_balance()

                result = "win" if profit > 0 else "loss" if profit < 0 else "draw"
                log_trade({**signal_res, "result": result, "retry": is_retry})

                # Reporte de resultado
                if profit > 0:
                    send_telegram_message(
                        f"GANADA (+${profit:.2f}) | Balance: ${new_balance:.2f}"
                    )
                elif profit < 0:
                    send_telegram_message(
                        f"PERDIDA ({profit:.2f}) | Balance: ${new_balance:.2f}"
                    )
                else:
                    send_telegram_message(
                        f"NEUTRA | Balance: ${new_balance:.2f}"
                    )

                current_balance = new_balance

                # ==== ACTUALIZAR META Y STOP DINÁMICAMENTE ====
                if USE_PERCENT_MODE:
                    # Siempre recalcular con el balance actual
                    target_balance = current_balance * (1 + STOP_WIN / 100)
                    stop_balance = current_balance * (1 - STOP_LOSS / 100)
                    logger.info(
                        f"Meta/Stop recalculados (modo %): "
                        f"${target_balance:.2f} / ${stop_balance:.2f}"
                    )
                else:
                    # Trailing solo si está habilitado y el balance creció
                    if TRAILING_STOP_ENABLED and current_balance > balance:
                        target_balance = current_balance * (
                            1 + TRAILING_STOP_WIN_PERCENT / 100
                        )
                        stop_balance = current_balance * (
                            1 - TRAILING_STOP_LOSS_PERCENT / 100
                        )
                        logger.info(
                            f"Trailing Stop -> Meta: {target_balance:.2f}, "
                            f"Stop: {stop_balance:.2f}"
                        )

                # ==== VERIFICAR LÍMITES ====
                if current_balance >= target_balance:
                    send_telegram_message("Meta alcanzada. Pausando bot.")
                    logger.info("Meta alcanzada. Fin de ejecución.")
                    break
                elif current_balance <= stop_balance:
                    send_telegram_message("Stop alcanzado. Finalizando bot.")
                    logger.info("Stop alcanzado. Fin de ejecución.")
                    break

            else:
                # ==== FALLÓ LA EJECUCIÓN ====
                retries = (failed_signal.get("retries", 0) if failed_signal else 0) + 1
                failed_signal = {**signal_res, "retries": retries}
                failed_signal_time = current_time

                attempt_msg = f"Intento {retries}/{MAX_RETRY_PER_SIGNAL + 1}"
                logger.warning(f"Falló ejecución ({attempt_msg})")
                send_telegram_message(
                    f"Falló entrada {direction.upper()}. {attempt_msg}"
                )

                if retries >= MAX_RETRY_PER_SIGNAL:
                    cooldown_msg = (
                        f"Señal {direction.upper()} descartada. "
                        f"Cooldown {SIGNAL_COOLDOWN_MINUTES} min."
                    )
                    logger.info(cooldown_msg)
                    send_telegram_message(cooldown_msg)
                    time.sleep(SIGNAL_COOLDOWN_SECONDS)
                else:
                    time.sleep(30)  # Espera antes del siguiente reintento

        else:
            time.sleep(5)


if __name__ == "__main__":
    main()