# utils/trade_logger.py
import os
import pandas as pd
from datetime import datetime
from typing import Dict, Any, Optional

TRADE_LOG_DIR = "trade_logs"
DEFAULT_LOG_FILE = os.path.join(TRADE_LOG_DIR, "unnamed_strategy_history.csv")

def log_trade(trade_data: Dict[str, Any]):
    """
    Registra una operación en un archivo CSV estructurado.
    Crea el archivo con cabeceras si no existe.
    El archivo se guarda en la carpeta 'trade_logs' y se nombra según la estrategia.
    """
    os.makedirs(TRADE_LOG_DIR, exist_ok=True)

    strategy_name = trade_data.get("strategy_name", "unnamed_strategy")
    # Limpiar el nombre para que sea un nombre de archivo válido
    safe_strategy_name = "".join(c for c in strategy_name if c.isalnum() or c in ('_', '-')).rstrip()
    log_file = os.path.join(TRADE_LOG_DIR, f"{safe_strategy_name}_history.csv")

    file_exists = os.path.isfile(log_file)

    # Añadir timestamp si no está presente
    if 'timestamp' not in trade_data:
        trade_data['timestamp'] = datetime.now()

    # Eliminar 'strategy_name' del diccionario para no duplicarlo en el CSV, ya está en el nombre del archivo.
    # trade_data.pop("strategy_name", None)

    df = pd.DataFrame([trade_data])

    # Reordenar columnas para consistencia, poniendo el resultado al final
    if 'result' in df.columns:
        cols = [c for c in df.columns if c != 'result'] + ['result']
        df = df[cols]

    df.to_csv(
        log_file,
        mode='a',
        header=not file_exists,
        index=False,
        date_format='%Y-%m-%d %H:%M:%S'
    )