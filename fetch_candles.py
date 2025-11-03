import os
import time
import pandas as pd
from iqoptionapi.stable_api import IQ_Option
from dotenv import load_dotenv

from utils.config_manager import get_settings

# --- Configuración base ---
load_dotenv()
settings = get_settings()

EMAIL = os.getenv("EMAIL")
PASSWORD = os.getenv("PASSWORD")

PAIR = settings.get("PAIR")
CANDLE_DURATION = settings.get("CANDLE_DURATION")
NUM_CANDLES = 2000       # Número de velas a descargar para el backtest
OUTPUT_DIR = "historical_data"

def fetch_and_save(pair: str, duration: int, num_candles: int):
    """Descarga datos históricos desde IQ Option y los guarda como CSV."""
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    file_path = os.path.join(OUTPUT_DIR, f"{pair}_{duration}s_{num_candles}c.csv")

    print(f"Conectando a IQ Option...")
    api = IQ_Option(EMAIL, PASSWORD)
    api.connect()

    if not api.check_connect():
        print("❌ No se pudo conectar. Revisa tu red o credenciales.")
        return

    print(f"✅ Conectado. Descargando {num_candles} velas de {pair} ({duration}s)...")
    end_time = time.time()

    candles = api.get_candles(pair, duration, num_candles, end_time)

    if not candles:
        print("⚠️ No se obtuvieron datos. Revisa que el mercado esté abierto o el par sea correcto.")
        return

    df = pd.DataFrame(candles)
    df.rename(columns={
        "open": "open",
        "max": "high",
        "min": "low",
        "close": "close",
        "volume": "volume"
    }, inplace=True)
    df["time"] = pd.to_datetime(df["from"], unit="s")
    df.set_index("time", inplace=True)

    df.to_csv(file_path)
    print(f"✅ Archivo guardado: {file_path}")
    print(f"Rango temporal: {df.index.min()} → {df.index.max()}")

    return df

if __name__ == "__main__":
    df = fetch_and_save(PAIR, CANDLE_DURATION, NUM_CANDLES)
