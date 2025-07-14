# utils/logger.py
import logging

def setup_logger():
    logger = logging.getLogger("TradingBot")
    logger.setLevel(logging.DEBUG)

    # Formato
    formatter = logging.Formatter('%(asctime)s — %(levelname)s — %(message)s')

    # Handler para consola
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)

    # Handler para archivo
    file_handler = logging.FileHandler("bot.log")
    file_handler.setFormatter(formatter)

    # Evitar duplicados
    if not logger.hasHandlers():
        logger.addHandler(console_handler)
        logger.addHandler(file_handler)

    return logger
