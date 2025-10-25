# utils/trade_logger.py
import os
import pandas as pd
from datetime import datetime
from typing import Dict, Any, Optional

TRADE_LOG_FILE = "trade_history.csv"

def log_trade(trade_data: Dict[str, Any]):
    """
    Registra una operación en un archivo CSV estructurado.
    Crea el archivo con cabeceras si no existe.
    """
    file_exists = os.path.isfile(TRADE_LOG_FILE)

    # Añadir timestamp si no está presente
    if 'timestamp' not in trade_data:
        trade_data['timestamp'] = datetime.now()

    df = pd.DataFrame([trade_data])

    # Reordenar columnas para consistencia, poniendo el resultado al final
    if 'result' in df.columns:
        cols = [c for c in df.columns if c != 'result'] + ['result']
        df = df[cols]

    df.to_csv(
        TRADE_LOG_FILE,
        mode='a',
        header=not file_exists,
        index=False,
        date_format='%Y-%m-%d %H:%M:%S'
    )