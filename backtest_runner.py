import importlib
import sys
import os
import json
import pandas as pd
import logging
import mplfinance as mpf

# --- LOGGING ---
logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("BacktestRunner")

# ✅ Usa el mapping REAL del proyecto
from utils.strategy_selector import AVAILABLE_STRATEGIES


# ------------------------------------------------------------
# ✅ Cargar datos históricos
# ------------------------------------------------------------
def load_historical_data(path: str) -> pd.DataFrame:
    if not os.path.exists(path):
        raise FileNotFoundError(f"No existe el archivo: {path}")

    logger.info(f"📂 Cargando datos desde: {path}")

    df = pd.read_csv(path)

    # Normaliza nombres importantes
    df = df.rename(columns={
        "open": "open",
        "high": "high",
        "low": "low",
        "close": "close",
        "timestamp": "timestamp",
        "time": "timestamp"
    })

    # Convertir timestamp
    if "timestamp" in df.columns:
        # Quitar unit="s" para que pandas lo interprete automáticamente
        df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce")
    else:
        raise ValueError("El CSV no tiene columna de timestamp.")

    df = df.dropna(subset=["timestamp"]).reset_index(drop=True)

    logger.info(f"✅ Velas cargadas: {len(df)}")
    return df


# ------------------------------------------------------------
# ✅ Detección automática del JSON correcto según el módulo
# ------------------------------------------------------------
def get_json_path(module_path: str) -> str:
    module_name = module_path.split(".")[-1]
    json_name = f"{module_name}_config.json"
    json_path = os.path.join("strategies", "bot", json_name)

    if not os.path.exists(json_path):
        raise FileNotFoundError(f"No existe el archivo JSON: {json_path}")

    return json_path


# ------------------------------------------------------------
# ✅ Backtest principal
# ------------------------------------------------------------
def run_backtest(strategy_key: str):
    # 1️⃣ Validar estrategia
    strategy_info = AVAILABLE_STRATEGIES.get(strategy_key)
    if not strategy_info:
        raise ValueError(f"No existe la estrategia con clave: {strategy_key}")

    module_path = strategy_info["module"]
    strategy_name = strategy_info["name"]

    logger.info(f"\n✅ Estrategia seleccionada: {strategy_name}")
    logger.info(f"📦 Módulo: {module_path}")

    # 2️⃣ Importar módulo
    strategy_module = importlib.import_module(module_path)

    # 3️⃣ Cargar JSON correcto
    json_path = get_json_path(module_path)

    logger.info(f"✅ Configuración cargada desde {json_path}")

    with open(json_path, "r") as f:
        full_config = json.load(f)

    # ✅ Los bots v3/v4/v5 usan NORMAL_PARAMS como estándar
    params = full_config.get("NORMAL_PARAMS", full_config)
    # Normalizar claves a minúsculas para que add_indicators funcione
    params = {k.lower(): v for k, v in params.items()}

    # 4️⃣ Cargar dataset
    folder = "historical_data"
    csv_files = [f for f in os.listdir(folder) if f.endswith(".csv")]

    if not csv_files:
        raise FileNotFoundError("No hay CSVs en /historical_data/")

    data_path = os.path.join(folder, csv_files[0])
    df = load_historical_data(data_path)

    # 5️⃣ Agregar indicadores
    if hasattr(strategy_module, "add_indicators"):
        df_ind = strategy_module.add_indicators(df.copy(), params)
    else:
        df_ind = df.copy()

    # 6️⃣ Detectar función principal (wrapper para backtest)
    analyze_func_name = strategy_info.get("function")
    if not hasattr(strategy_module, analyze_func_name):
        raise RuntimeError(f"La función '{analyze_func_name}' no se encontró en el módulo {module_path}")
    analyze_func = getattr(strategy_module, analyze_func_name)

    logger.info("🚀 Ejecutando backtest...")
    # 7️⃣ Simulación
    results = []

    for i in range(len(df_ind)):
        sub = df_ind.iloc[:i + 1]
        # Corregido: Pasar los parámetros a la función de la estrategia
        signal = analyze_func(sub, params)
        
        if signal:
            # --- Simulación del resultado de la operación ---
            entry_price = sub.iloc[-1]["close"]
            duration_minutes = signal.get("duration_minutes", 1) # Asume 1 min si no se especifica
            
            # El índice de salida es N velas en el futuro
            exit_index = i + duration_minutes
            
            result = None
            if exit_index < len(df_ind):
                exit_price = df_ind.iloc[exit_index]["close"]
                
                if signal["direction"] == "call":
                    if exit_price > entry_price:
                        result = "win"
                    elif exit_price < entry_price:
                        result = "loss"
                    else:
                        result = "draw"
                elif signal["direction"] == "put":
                    if exit_price < entry_price:
                        result = "win"
                    elif exit_price > entry_price:
                        result = "loss"
                    else:
                        result = "draw"

            results.append({
                "timestamp": sub.iloc[-1]["timestamp"],
                "direction": signal["direction"],
                "close": sub.iloc[-1]["close"],
                "result": result # Añadimos el resultado
            })

    # 8️⃣ Guardar resultados
    os.makedirs("results", exist_ok=True)
    result_path = f"results/backtest_{strategy_key}.csv"
    pd.DataFrame(results).to_csv(result_path, index=False)

    logger.info(f"✅ Resultados guardados en: {result_path}")

    # 9️⃣ Métricas básicas (placeholder)
    results_df = pd.DataFrame(results)
    total_trades = len(results_df)

    # Corregido: Manejar el caso donde no hay operaciones
    if total_trades == 0:
        logger.info("\n--- 📊 RESUMEN ---")
        logger.warning("🤷 No se generaron operaciones durante el backtest con la configuración actual.")
        return

    wins = len(results_df[results_df['result'] == 'win'])
    losses = len(results_df[results_df['result'] == 'loss'])
    draws = len(results_df[results_df['result'] == 'draw'])
    winrate = (wins / total_trades) * 100 if total_trades > 0 else 0

    logger.info(f"\n--- 📊 RESUMEN ---")
    logger.info(f"Total de operaciones: {total_trades}")
    logger.info(f"Ganadas: {wins}")
    logger.info(f"Perdidas: {losses}")
    logger.info(f"Empates: {draws}")
    logger.info(f"Winrate: {winrate:.2f}%")




# ------------------------------------------------------------
# ✅ MAIN
# ------------------------------------------------------------
if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Uso: py backtest_runner.py <strategy_key>")
        sys.exit(1)

    strategy_key = sys.argv[1]
    run_backtest(strategy_key)
