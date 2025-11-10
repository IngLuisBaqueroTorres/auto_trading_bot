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
    AMOUNT = settings.get("AMOUNT", 1.0)  # ← ENTRADA FIJA: $1.00
    DURATION = settings.get("DURATION", 1)
    USE_PERCENT_MODE = settings.get("USE_PERCENT_MODE", False)
    MAX_RETRY_PER_SIGNAL = settings.get("MAX_RETRY_PER_SIGNAL", 1)
    SIGNAL_COOLDOWN_MINUTES = settings.get("SIGNAL_COOLDOWN_MINUTES", 1)
    SIGNAL_COOLDOWN_SECONDS = SIGNAL_COOLDOWN_MINUTES * 60

    # === STOP WIN/LOSS: SEGÚN MODO (solo trailing o fijo) ===
    if USE_PERCENT_MODE:
        STOP_WIN = settings.get("TRAILING_STOP_WIN_PERCENT", 2.0)
        STOP_LOSS = settings.get("TRAILING_STOP_LOSS_PERCENT", 1.0)
    else:
        STOP_WIN = settings.get("STOP_WIN", 10.0)
        STOP_LOSS = settings.get("STOP_LOSS", 5.0)

    # === CARGAR ESTRATEGIA DINÁMICAMENTE ===
    STRATEGY_NAME = settings.get("STRATEGY", "self_adjusting_strategy_v6")
    logger.info(f"Solicitando estrategia: {STRATEGY_NAME}")

    strategy_info = AVAILABLE_STRATEGIES.get(STRATEGY_NAME)
    if not strategy_info:
        logger.error(f"Estrategia '{STRATEGY_NAME}' no encontrada. Opciones: {list(AVAILABLE_STRATEGIES.keys())}")
        send_telegram_message(f"Estrategia '{STRATEGY_NAME}' no existe.")
        return

    try:
        module = importlib.import_module(strategy_info["module"])
        selected_strategy = getattr(module, strategy_info["function"])
        if not callable(selected_strategy):
            raise AttributeError("La función no es callable")
        logger.info(f"Estrategia cargada: {strategy_info['name']} ({selected_strategy.__name__})")
    except Exception as e:
        logger.error(f"Error al cargar estrategia: {e}")
        send_telegram_message("Error crítico al cargar estrategia.")
        return

    # === Conexión con IQ Option ===
    EMAIL = settings.get("EMAIL")
    PASSWORD = settings.get("PASSWORD")

    API = connect_iq_option(EMAIL, PASSWORD)
    if API is None:
        return

    API.change_balance(BALANCE_MODE)
    initial_balance = API.get_balance()
    current_balance = initial_balance

    # === CONFIGURAR STOP WIN / LOSS SEGÚN MODO ===
    if not USE_PERCENT_MODE:
        # MODO FIJO EN DÓLARES
        target_balance = initial_balance + STOP_WIN
        stop_balance = initial_balance - STOP_LOSS
        entry_text = f"${AMOUNT:.2f}"

        logger.info(f"Modo FIJO: +${STOP_WIN} / -${STOP_LOSS}")
        logger.info(f"Objetivo: ${target_balance:.2f} | Stop: ${stop_balance:.2f}")

        send_telegram_message(
            f"Bot iniciado (FIJO)\n"
            f"Balance: ${initial_balance:.2f}\n"
            f"Objetivo: +${STOP_WIN} → ${target_balance:.2f}\n"
            f"Stop Loss: -${STOP_LOSS} → ${stop_balance:.2f}\n"
            f"Entrada: ${AMOUNT:.2f}"
        )
    else:
        # MODO PORCENTUAL (solo trailing)
        target_balance = initial_balance * (1 + STOP_WIN / 100)
        stop_balance = initial_balance * (1 - STOP_LOSS / 100)
        entry_text = f"${AMOUNT:.2f}"

        logger.info(f"Modo PORCENTUAL (trailing): +{STOP_WIN}% / -{STOP_LOSS}%")
        logger.info(f"Meta inicial: ${target_balance:.2f} | Stop: ${stop_balance:.2f}")

        send_telegram_message(
            f"Bot iniciado (TRAILING)\n"
            f"Balance: ${initial_balance:.2f}\n"
            f"Meta: +{STOP_WIN}% → ${target_balance:.2f}\n"
            f"Stop Loss: -{STOP_LOSS}% → ${stop_balance:.2f}\n"
            f"Entrada: ${AMOUNT:.2f} fijo"
        )

    # === VARIABLES DE CONTROL ===
    last_signal = None
    last_order_time = 0
    failed_signal = None
    failed_signal_time = 0
    total_pnl = 0.0

    while True:
        # ---- Reconexión automática ----
        if not API.check_connect():
            logger.warning("Conexión perdida. Reintentando...")
            send_telegram_message("Conexión perdida. Reintentando...")
            API = connect_iq_option(EMAIL, PASSWORD)
            if API is None:
                send_telegram_message("Falló reconexión. Bot detenido.")
                break
            API.change_balance(BALANCE_MODE)
            continue

        # ---- Mercado cerrado ----
        if not is_market_open(API, PAIR):
            logger.warning(f"Mercado cerrado para {PAIR}. Esperando...")
            time.sleep(600)
            continue

        # ---- Obtener velas ----
        candles = get_candle_dataframe(API, PAIR, 60, 100)
        if candles is None or len(candles) < 50:
            time.sleep(5)
            continue

        # ---- Filtro de Noticias (NUEVO) ----
        try:
            all_news = fetch_high_impact_news()
            relevant_news = is_relevant_for_pair(all_news, PAIR)
            if is_news_time(datetime.now(), relevant_news, before=20, after=10):
                logger.warning(f"Noticia de alto impacto cercana para {PAIR}. Pausando operaciones.")
                send_telegram_message(f"Pausa por noticia en {PAIR}. Reanudando en 10-20 min.")
                time.sleep(300)
                continue
        except Exception as e:
            logger.error(f"Error al comprobar noticias: {e}")
            time.sleep(60)

        # ---- Generar señal ----
        signal_res = selected_strategy(candles, last_signal, current_hour=datetime.now().hour)
        if not signal_res:
            time.sleep(5)
            continue

        direction = signal_res.get("direction")
        current_time = time.time()

        # Evitar repetición rápida
        if signal_res == last_signal and (current_time - last_order_time) < 70:
            time.sleep(60)
            continue

        # Reintentos por fallo
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

        # ========================================
        # 1. ENTRADA: SIEMPRE DEL SETTINGS
        # ========================================
        balance = API.get_balance()
        trade_amount = AMOUNT  # ← ENTRADA FIJA: $1.00
        entry_text = f"${trade_amount:.2f}"

        # CUENTA REAL: mínimo $1.00
        if BALANCE_MODE == "REAL" and trade_amount < 1.0:
            old_amount = trade_amount
            trade_amount = 1.0
            entry_text = f"${trade_amount:.2f} (forzado desde ${old_amount:.2f})"
            logger.warning(f"Forzando entrada: ${old_amount:.2f} → $1.00")
            send_telegram_message(f"Entrada ajustada: ${old_amount:.2f} → $1.00 (mínimo real)")

        # Validación de balance
        if balance < trade_amount * 1.2:
            msg = f"Balance bajo: ${balance:.2f} < ${trade_amount * 1.2:.2f}"
            logger.warning(msg)
            send_telegram_message(msg)
            time.sleep(300)
            continue

        logger.info(f"ENTRADA CONFIRMADA: ${trade_amount:.2f}")

        retry_text = " (reintento)" if is_retry else ""
        msg = f"Señal{retry_text} en <b>{PAIR}</b>: <b>{direction.upper()}</b>"
        logger.info(msg)
        send_telegram_message(msg)

        # ---- Ejecutar orden ----
        order_success = False
        order_id = None
        try:
            status, order_id = API.buy(trade_amount, PAIR, direction, DURATION)
            if status:
                order_success = True
                logger.info(f"Orden ejecutada: {PAIR} {direction.upper()} ${trade_amount:.2f}")
                send_telegram_message(f"Operación abierta: {direction.upper()} ${trade_amount:.2f}")
            else:
                error_msg = f"API.buy FALLÓ → status={status}, id={order_id}, monto=${trade_amount:.2f}"
                logger.warning(error_msg)
                send_telegram_message(error_msg)
        except Exception as e:
            logger.error(f"Error al ejecutar orden: {e}")
            send_telegram_message(f"Error ejecutando orden: {e}")

        # ==== ÉXITO DE LA OPERACIÓN ====
        if order_success:
            last_signal = signal_res
            last_order_time = current_time
            failed_signal = None

            time.sleep(DURATION * 60 + 5)
            profit = API.check_win_v3(order_id)
            new_balance = API.get_balance()
            total_pnl += profit

            result = "win" if profit > 0 else "loss" if profit < 0 else "draw"
            log_trade({**signal_res, "result": result, "profit": profit, "balance": new_balance})

            # Reporte
            pnl_text = f"P&L: {total_pnl:+.2f}"
            if profit > 0:
                send_telegram_message(f"GANADA +${profit:.2f} | {pnl_text} | ${new_balance:.2f}")
            elif profit < 0:
                send_telegram_message(f"PERDIDA {profit:.2f} | {pnl_text} | ${new_balance:.2f}")
            else:
                send_telegram_message(f"NEUTRA | {pnl_text} | ${new_balance:.2f}")

            current_balance = new_balance

            # ===================================================================
            # === LÓGICA DE STOP SEGÚN MODO ===
            # ===================================================================

            if not USE_PERCENT_MODE:
                # MODO FIJO: detener en cualquier límite
                if current_balance >= target_balance:
                    send_telegram_message(f"OBJETIVO FIJO ALCANZADO: +${STOP_WIN}\nBot detenido.")
                    logger.info("Stop Win fijo alcanzado.")
                    break
                if current_balance <= stop_balance:
                    send_telegram_message(f"STOP LOSS FIJO: -${STOP_LOSS}\nBot detenido.")
                    logger.info("Stop Loss fijo alcanzado.")
                    break

            else:
                # MODO PORCENTUAL: trailing solo en WIN
                if current_balance >= target_balance:
                    old_target = target_balance
                    target_balance = current_balance * (1 + STOP_WIN / 100)
                    stop_balance = current_balance * (1 - STOP_LOSS / 100)

                    send_telegram_message(
                        f"META +{STOP_WIN}% ALCANZADA → NUEVA META: ${target_balance:.2f}\n"
                        f"Stop Loss: ${stop_balance:.2f}\n"
                        f"¡Seguimos operando!"
                    )
                    logger.info(f"Trailing activado: meta → ${target_balance:.2f}, stop → ${stop_balance:.2f}")

                # STOP LOSS DEFINITIVO
                if current_balance <= stop_balance:
                    send_telegram_message(
                        f"STOP LOSS CRÍTICO (-{STOP_LOSS}%) → ${current_balance:.2f}\n"
                        f"Bot detenido por seguridad."
                    )
                    logger.info("Stop Loss porcentual alcanzado. Fin.")
                    break

        else:
            # ==== FALLÓ LA EJECUCIÓN ====
            retries = (failed_signal.get("retries", 0) if failed_signal else 0) + 1
            failed_signal = {**signal_res, "retries": retries}
            failed_signal_time = current_time

            attempt_msg = f"Intento {retries}/{MAX_RETRY_PER_SIGNAL + 1}"
            logger.warning(f"Falló ejecución ({attempt_msg})")
            send_telegram_message(f"Falló entrada {direction.upper()}. {attempt_msg}")

            if retries >= MAX_RETRY_PER_SIGNAL:
                cooldown_msg = f"Señal {direction.upper()} descartada. Cooldown {SIGNAL_COOLDOWN_MINUTES} min."
                logger.info(cooldown_msg)
                send_telegram_message(cooldown_msg)
                time.sleep(SIGNAL_COOLDOWN_SECONDS)
            else:
                time.sleep(30)


if __name__ == "__main__":
    main()