# backtest_runner.py
import importlib
import sys
import os
import json
import pandas as pd
import logging

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("BacktestRunner")

from utils.strategy_selector import AVAILABLE_STRATEGIES

def load_historical_data(path: str) -> pd.DataFrame:
    if not os.path.exists(path):
        raise FileNotFoundError(f"No existe el archivo: {path}")
    logger.info(f"Cargando datos desde: {path}")
    df = pd.read_csv(path)
    df = df.rename(columns={"time": "timestamp", "open": "open", "high": "high", "low": "low", "close": "close"})
    df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce")
    df = df.dropna(subset=["timestamp"]).reset_index(drop=True)
    logger.info(f"Velas cargadas: {len(df)}")
    return df

def get_json_path(module_path: str) -> str:
    module_name = module_path.split(".")[-1]
    json_name = f"{module_name}_config.json"
    json_path = os.path.join("strategies", "bot", json_name)
    if not os.path.exists(json_path):
        raise FileNotFoundError(f"No existe el archivo JSON: {json_path}")
    return json_path

def run_backtest(strategy_key: str):
    strategy_info = AVAILABLE_STRATEGIES.get(strategy_key)
    if not strategy_info:
        raise ValueError(f"No existe la estrategia con clave: {strategy_key}")

    module_path = strategy_info["module"]
    strategy_name = strategy_info["name"]
    logger.info(f"\nEstrategia seleccionada: {strategy_name}")
    logger.info(f"Módulo: {module_path}")

    strategy_module = importlib.import_module(module_path)
    json_path = get_json_path(module_path)
    logger.info(f"Configuración cargada desde {json_path}")

    with open(json_path, "r") as f:
        full_config = json.load(f)

    params = full_config.get("NORMAL_PARAMS", full_config)
    params = {k.lower(): v for k, v in params.items()}

    folder = "historical_data"
    csv_files = [f for f in os.listdir(folder) if f.endswith(".csv")]
    if not csv_files:
        raise FileNotFoundError("No hay CSVs en /historical_data/")
    data_path = os.path.join(folder, csv_files[0])
    df = load_historical_data(data_path)

    if hasattr(strategy_module, "add_indicators"):
        df_ind = strategy_module.add_indicators(df.copy(), params)
    else:
        df_ind = df.copy()

    analyze_func_name = strategy_info.get("function")
    if not hasattr(strategy_module, analyze_func_name):
        raise RuntimeError(f"La función '{analyze_func_name}' no se encontró en el módulo {module_path}")
    analyze_func = getattr(strategy_module, analyze_func_name)

    logger.info("Ejecutando backtest...")
    results = []

    for i in range(len(df_ind)):
        sub = df_ind.iloc[:i + 1]
        signal = analyze_func(sub, params)

        if signal:
            entry_price = sub.iloc[-1]["close"]
            duration_minutes = signal.get("duration_minutes", 1)
            exit_index = i + duration_minutes

            result = None
            if exit_index < len(df_ind):
                exit_price = df_ind.iloc[exit_index]["close"]
                if signal["direction"] == "call":
                    result = "win" if exit_price > entry_price else "loss" if exit_price < entry_price else "draw"
                elif signal["direction"] == "put":
                    result = "win" if exit_price < entry_price else "loss" if exit_price > entry_price else "draw"

            # GUARDAR RSI Y BB_WIDTH
            last_row = sub.iloc[-1]
            results.append({
                "timestamp": last_row["timestamp"],
                "direction": signal["direction"],
                "close": last_row["close"],
                "rsi": round(last_row.get("rsi", 0), 2),
                "bb_width": round(last_row.get("bb_width", 0), 6),
                "result": result
            })

    os.makedirs("results", exist_ok=True)
    result_path = f"results/backtest_{strategy_key}.csv"
    pd.DataFrame(results).to_csv(result_path, index=False)
    logger.info(f"Resultados guardados en: {result_path}")

    results_df = pd.DataFrame(results)
    total_trades = len(results_df)
    if total_trades == 0:
        logger.info("\n--- RESUMEN ---")
        logger.warning("No se generaron operaciones durante el backtest con la configuración actual.")
        return

    wins = len(results_df[results_df['result'] == 'win'])
    losses = len(results_df[results_df['result'] == 'loss'])
    draws = len(results_df[results_df['result'] == 'draw'])
    winrate = (wins / total_trades) * 100

    logger.info(f"\n--- RESUMEN ---")
    logger.info(f"Total de operaciones: {total_trades}")
    logger.info(f"Ganadas: {wins}")
    logger.info(f"Perdidas: {losses}")
    logger.info(f"Empates: {draws}")
    logger.info(f"Winrate: {winrate:.2f}%")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Uso: py backtest_runner.py <strategy_key>")
        sys.exit(1)
    strategy_key = sys.argv[1]
    run_backtest(strategy_key)