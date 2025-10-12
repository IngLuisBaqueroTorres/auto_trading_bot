import logging
import os
from datetime import datetime

def setup_logger():
    logger = logging.getLogger("TradingBot")
    logger.setLevel(logging.DEBUG)

    # Crear carpeta "logs" si no existe
    log_dir = "logs"
    os.makedirs(log_dir, exist_ok=True)

    # Nombre del archivo diario (ej: logs/bot_2025-10-07.log)
    log_filename = os.path.join(log_dir, f"bot_{datetime.now().strftime('%Y-%m-%d')}.log")

    # Formato del log
    formatter = logging.Formatter('%(asctime)s — %(levelname)s — %(message)s')

    # Handler para consola
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)

    # Handler para archivo diario
    file_handler = logging.FileHandler(log_filename, encoding='utf-8')
    file_handler.setFormatter(formatter)

    # Evitar handlers duplicados
    if not logger.hasHandlers():
        logger.addHandler(console_handler)
        logger.addHandler(file_handler)

    logger.info(f"🗓️ Iniciando registro en archivo: {log_filename}")
    return logger
