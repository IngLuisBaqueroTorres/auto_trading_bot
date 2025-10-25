# utils/config_manager.py
import os
import shutil

STRATEGY_DIR = "strategies/bot"
CONFIG_FILENAME = "self_adjusting_v1_config.json"
CONFIG_PATH = os.path.join(STRATEGY_DIR, CONFIG_FILENAME)
VERSIONS_DIR = os.path.join(STRATEGY_DIR, "config_versions")

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