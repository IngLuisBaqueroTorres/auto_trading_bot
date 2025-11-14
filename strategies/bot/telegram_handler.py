# utils/telegram_handler.py
import os
import logging
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes, MessageHandler, filters

from .bot_controller import start_bot, stop_bot, get_status, get_balance

logger = logging.getLogger("TelegramHandler")


# === CONFIGURACIÓN PRINCIPAL ===
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")  # Asegúrate que sea TELEGRAM_BOT_TOKEN como en tu otro archivo

# === COMANDOS ===

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Mensaje de bienvenida y ayuda."""
    help_text = (
        "🤖 ¡Hola! Soy el asistente de tu Bot de Trading.\n\n"
        "Comandos disponibles:\n"
        "▶️ `/run <estrategia>` - Inicia el bot (ej: `/run self_adjusting_v7`).\n"
        "🛑 `/stop` - Detiene el bot.\n"
        "📊 `/status` - Muestra el estado actual del bot.\n"
        "💰 `/balance` - Consulta el balance actual de la cuenta.\n"
        "👋 `/start` - Muestra este mensaje de ayuda."
    )
    await update.message.reply_text(help_text)
    logger.info("Comando /start recibido, ayuda enviada.")


async def run_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Inicia el bot con una estrategia específica."""
    if not context.args:
        await update.message.reply_text("❗ Debes especificar una estrategia. Ejemplo: `/run self_adjusting_v7`")
        return

    strategy_key = context.args[0].lower()
    msg = start_bot(strategy_key)
    await update.message.reply_text(msg)
    logger.info(f"Intento de inicio para '{strategy_key}' vía Telegram.")


async def stop_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Detiene el bot."""
    msg = stop_bot()
    await update.message.reply_text(msg)
    logger.info("Comando /stop recibido.")


async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Muestra el estado actual del bot."""
    state = get_status()
    status_text = (
        f"📊 **Estado Actual**\n"
        f"- **Estrategia**: `{state['bot']}`\n"
        f"- **Activo**: {'Sí' if state['active'] else 'No'}\n"
        f"- **PID**: `{state.get('pid', 'N/A')}`"
    )
    await update.message.reply_text(status_text, parse_mode='MarkdownV2')

async def balance_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Consulta y muestra el balance actual."""
    await update.message.reply_text("Consultando balance, por favor espera...")
    balance_str = get_balance()
    await update.message.reply_text(f"💰 Balance actual: {balance_str}")
    logger.info(f"Comando /balance ejecutado. Resultado: {balance_str}")


async def unknown_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Manejador para comandos no reconocidos."""
    await update.message.reply_text("❔ Comando no reconocido. Usa /start para ver las opciones.")


# === INICIALIZADOR DEL TELEGRAM BOT ===

def start_telegram_listener():
    """Configura y ejecuta el bot de Telegram en modo polling."""
    if not BOT_TOKEN:
        logger.error("El token del bot de Telegram (TELEGRAM_BOT_TOKEN) no está configurado en .env")
        return

    app = ApplicationBuilder().token(BOT_TOKEN).build()

    # Comandos principales
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("run", run_command))
    app.add_handler(CommandHandler("stop", stop_command))
    app.add_handler(CommandHandler("status", status_command))
    app.add_handler(CommandHandler("balance", balance_command))

    # Manejador para comandos desconocidos
    app.add_handler(MessageHandler(filters.COMMAND, unknown_command))

    logger.info("🚀 Telegram listener activo y escuchando comandos.")
    app.run_polling()