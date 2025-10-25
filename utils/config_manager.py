# utils/config_manager.py
import os
import shutil
import json
from dotenv import load_dotenv, set_key

STRATEGY_DIR = "strategies/bot"
CONFIG_FILENAME = "self_adjusting_v1_config.json"
CONFIG_PATH = os.path.join(STRATEGY_DIR, CONFIG_FILENAME)
VERSIONS_DIR = os.path.join(STRATEGY_DIR, "config_versions")
SETTINGS_FILE = "settings.json"
ENV_FILE = ".env"

def get_settings():
    """Lee la configuración desde settings.json y .env."""
    # Cargar variables de entorno
    load_dotenv(ENV_FILE)
    
    # Valores por defecto para settings.json
    defaults = {
        "BALANCE_MODE": "PRACTICE",
        "PAIR": "EURUSD-OTC",
        "AMOUNT": 1,
        "DURATION": 1,
        "STOP_WIN": 10,
        "STOP_LOSS": 10,
        "CANDLE_DURATION": 60,
        "NUM_CANDLES": 200
    }

    if not os.path.exists(SETTINGS_FILE):
        return defaults

    with open(SETTINGS_FILE, 'r') as f:
        settings = json.load(f)
        # Asegurar que todas las claves por defecto existan
        for key, value in defaults.items():
            settings.setdefault(key, value)
        return settings

def save_settings(new_settings: dict):
    """Guarda la configuración en settings.json y .env."""
    # Guardar credenciales en .env
    set_key(ENV_FILE, "EMAIL", new_settings.pop("EMAIL", ""))
    set_key(ENV_FILE, "PASSWORD", new_settings.pop("PASSWORD", ""))

    # Guardar el resto en settings.json
    with open(SETTINGS_FILE, 'w') as f:
        json.dump(new_settings, f, indent=4)
        
def restore_last_config():
    """
    Restaura la penúltima configuración guardada desde el directorio de versiones.
    Se asume que la última es la que falló.
    """
    if not os.path.exists(VERSIONS_DIR):
        print("⚠️ No existe el directorio de versiones. No se puede restaurar.")
        return

    # Ordenar de más reciente a más antiguo
    backups = sorted([f for f in os.listdir(VERSIONS_DIR) if f.endswith(".json")], reverse=True)

    if len(backups) > 1:
        restore_from = os.path.join(VERSIONS_DIR, backups[1]) # La [0] es la que acaba de fallar, la [1] es la anterior buena
        shutil.copy(restore_from, CONFIG_PATH)
        print(f"🔄 Configuración restaurada desde la versión estable: {backups[1]}")
    else:
        print("⚠️ No hay suficientes versiones de configuración para realizar un rollback.")