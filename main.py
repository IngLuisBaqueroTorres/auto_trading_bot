import time
import importlib
from datetime import datetime
from iqoptionapi.stable_api import IQ_Option

from config import EMAIL, PASSWORD
from utils.helpers import get_candle_dataframe, is_market_open
from utils.telegram_notifier import send_telegram_message
from utils.logger import setup_logger
from utils.config_manager import get_settings
from utils.strategy_selector import AVAILABLE_STRATEGIES
from utils.trade_logger import log_trade
from utils.news_fetcher import fetch_high_impact_news, is_news_time

logger = setup_logger()


def calculate_dynamic_targets(API, settings):
    balance = API.get_balance()

    if settings["USE_PERCENT_MODE"] and settings["TRAILING_STOP_ENABLED"]:
        stop_win = balance * (settings["TRAILING_STOP_WIN_PERCENT"] / 100)
        stop_loss = balance * (settings["TRAILING_STOP_LOSS_PERCENT"] / 100)
    else:
        stop_win = settings["STOP_WIN"]
        stop_loss = settings["STOP_LOSS"]

    return balance, stop_win, stop_loss


def main(strategy_key):
    settings = get_settings()
    API = IQ_Option(EMAIL, PASSWORD)

    PAIR = settings["PAIR"]
    DURATION = settings["DURATION"]
    MIN_PAYOUT = settings["MIN_PAYOUT"]
    trade_amount = settings["AMOUNT"]

    logger.info(f"=== Bot iniciado con estrategia: {strategy_key} ===")

    connected, reason = API.connect()
    if not connected:
        logger.error(f"No conecta: {reason}")
        send_telegram_message(f"❌ Error conectando: {reason}")
        return

    API.change_balance(settings["BALANCE_MODE"])

    # === Estrategia cargada dinámicamente ===
    strategy_info = AVAILABLE_STRATEGIES[strategy_key]
    module = importlib.import_module(strategy_info["module"])
    selected_strategy = getattr(module, strategy_info["function"])

    # === Calcular metas ===
    initial_balance, stop_win, stop_loss = calculate_dynamic_targets(API, settings)
    current_target = initial_balance + stop_win
    lower_limit = initial_balance - stop_loss

    # === ENVIAR INFORMACIÓN DETALLADA A TELEGRAM ===
    if settings["USE_PERCENT_MODE"] and settings["TRAILING_STOP_ENABLED"]:
        msg = (
            f"🚀 Bot iniciado\n"
            f"📌 Estrategia: {strategy_key}\n"
            f"💱 Par: {PAIR}\n"
            f"💵 Balance inicial: {initial_balance}\n\n"
            f"📊 Modo: *Porcentual*\n"
            f"➡️ STOP WIN: {stop_win:.2f} ({settings['TRAILING_STOP_WIN_PERCENT']}%)\n"
            f"➡️ STOP LOSS: {stop_loss:.2f} ({settings['TRAILING_STOP_LOSS_PERCENT']}%)\n"
            f"🎯 Meta inicial: {current_target:.2f}\n"
        )
    else:
        msg = (
            f"🚀 Bot iniciado\n"
            f"📌 Estrategia: {strategy_key}\n"
            f"💱 Par: {PAIR}\n"
            f"💵 Balance inicial: {initial_balance}\n\n"
            f"📊 Modo: *Fijo*\n"
            f"➡️ STOP WIN fijo: {stop_win}\n"
            f"➡️ STOP LOSS fijo: {stop_loss}\n"
            f"🎯 Meta inicial: {current_target:.2f}\n"
        )

    send_telegram_message(msg)

    last_signal = None
    last_order_time = 0
    skip_news_until = 0

    while True:
        try:
            now_ts = time.time()
            now = datetime.now()

            # === 1. Mercado abierto REAL ===
            if not is_market_open(API, PAIR):
                logger.info("Mercado cerrado. Esperando…")
                time.sleep(60)
                continue

            # === 2. Noticias fuertes ===
            if now_ts > skip_news_until:
                news_events = fetch_high_impact_news()

                if news_events and is_news_time(now, news_events):
                    send_telegram_message("⛔ Noticias fuertes — pausa 5 minutos")
                    skip_news_until = now_ts + 300
                    time.sleep(60)
                    continue

            # === 3. Control SL / SW ===
            balance = API.get_balance()

            if balance <= lower_limit:
                send_telegram_message(
                    f"🟥 STOP LOSS alcanzado\nBalance final: {balance}"
                )
                return

            if balance >= current_target:
                if settings["USE_PERCENT_MODE"] and settings["TRAILING_STOP_ENABLED"]:
                    send_telegram_message(
                        "🟩 Meta porcentual alcanzada → recalculando metas…"
                    )

                    current_balance = balance
                    stop_win = current_balance * (
                        settings["TRAILING_STOP_WIN_PERCENT"] / 100
                    )
                    current_target = current_balance + stop_win

                else:
                    send_telegram_message(
                        f"🟩 STOP WIN alcanzado\nBalance final: {balance}"
                    )
                    return

            # === 4. Payout mínimo ===
            payout = API.get_digital_payout(PAIR)
            if payout is None or payout < MIN_PAYOUT:
                time.sleep(60)
                continue

            # === 5. Velas ===
            candles = get_candle_dataframe(API, PAIR, 60, 20)
            if candles is None or len(candles) < 20:
                time.sleep(5)
                continue

            # === 6. Señal ===
            signal = selected_strategy(candles, last_signal, current_hour=now.hour)

            if not signal:
                last_signal = None
                time.sleep(1)
                continue

            direction = signal.get("direction")

            # Evitar doble entrada muy seguida en la misma dirección
            if last_signal and direction == last_signal.get("direction"):
                if (now_ts - last_order_time) < 70:
                    time.sleep(2)
                    continue

            # === 7. Operación ===
            status, order_id = API.buy_digital_spot(
                PAIR, trade_amount, direction, DURATION
            )
            if not status:
                send_telegram_message("❌ Error enviando la operación.")
                continue

            check, win_amount = API.check_win_digital_v2(order_id)
            result = "WIN" if win_amount > 0 else "LOSS"
            profit = round(win_amount, 3)

            send_telegram_message(f"🎯 {result} | Ganancia: {profit}")
            log_trade(result, profit, direction, PAIR, trade_amount, signal)

            last_signal = signal
            last_order_time = now_ts
            time.sleep(2)

        except Exception as e:
            logger.error(f"Error ciclo: {e}")
            time.sleep(5)
            continue


if __name__ == "__main__":
    import sys
    strategy_key = sys.argv[1] if len(sys.argv) > 1 else "markII"
    main(strategy_key)
