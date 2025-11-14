# core/bot_controller.py
import subprocess
import os
import json
from typing import Optional, Dict, Any

from iqoptionapi.stable_api import IQ_Option
from utils.config_manager import get_settings
from utils.logger import setup_logger

# --- Estado del Bot (simulado en memoria) ---

bot_process: Optional[subprocess.Popen] = None
bot_state: Dict[str, Any] = {
    "bot": "Ninguno",
    "active": False,
    "pair": "N/A",
    "balance": 0.0,
    "winrate": 0.0,
    "pid": None
}

logger = setup_logger()

def start_bot(strategy_key: str) -> str:
    """Inicia el bot de trading en un nuevo proceso."""
    global bot_process, bot_state
    if bot_process and bot_process.poll() is None:
        return f"⚠️ El bot ya está en ejecución (PID: {bot_process.pid}). Usa /stop primero."

    command = ["python", "main.py", strategy_key]
    
    # Usamos Popen para tener control sobre el proceso
    bot_process = subprocess.Popen(command, creationflags=subprocess.CREATE_NEW_PROCESS_GROUP)
    
    bot_state.update({
        "bot": strategy_key,
        "active": True,
        "pid": bot_process.pid
    })
    return f"✅ Bot iniciado con la estrategia '{strategy_key}' (PID: {bot_process.pid})."

def stop_bot() -> str:
    """Detiene el proceso del bot de trading si está en ejecución."""
    global bot_process, bot_state
    if bot_process and bot_process.poll() is None:
        pid = bot_process.pid
        bot_process.terminate() # Envía una señal de terminación
        bot_process = None
        bot_state["active"] = False
        return f"🛑 Bot detenido (PID: {pid})."
    return "ℹ️ El bot no estaba en ejecución."

def get_status() -> Dict[str, Any]:
    """Devuelve el estado actual del bot."""
    if bot_process and bot_process.poll() is not None:
        bot_state["active"] = False # El proceso terminó por su cuenta
    return bot_state

def get_balance() -> str:
    """
    Se conecta a IQ Option, obtiene el balance y se desconecta.
    Devuelve un string con el balance o un mensaje de error.
    """
    settings = get_settings()
    email = settings.get("EMAIL")
    password = settings.get("PASSWORD")
    mode = settings.get("BALANCE_MODE", "PRACTICE").upper()

    if not email or not password:
        logger.error("Credenciales no encontradas para obtener balance.")
        return "Error: Credenciales no configuradas."

    API = IQ_Option(email, password)
    API.connect()

    if API.check_connect():
        logger.info(f"Conexión temporal para obtener balance en modo {mode}.")
        API.change_balance(mode)
        balance = API.get_balance()
        return f"${balance:,.2f} ({mode})"
    else:
        logger.error("No se pudo conectar a IQ Option para obtener el balance.")
        return "Error: No se pudo conectar a IQ Option."