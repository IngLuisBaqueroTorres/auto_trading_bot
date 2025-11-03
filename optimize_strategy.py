# optimize_strategy.py
import pandas as pd
import numpy as np
import os
import json
import shutil
from datetime import datetime

TRADE_LOG_FILE = "trade_logs/self_adjusting_v1_history.csv"
STRATEGY_DIR = "strategies/bot"
CONFIG_FILENAME = "self_adjusting_v1_config.json"
CONFIG_PATH = os.path.join(STRATEGY_DIR, CONFIG_FILENAME)
VERSIONS_DIR = os.path.join(STRATEGY_DIR, "config_versions")
HISTORY_SUMMARY_FILE = "history_summary.json"

def update_config_file(new_params: dict):
    """
    Actualiza el archivo de configuración, crea un backup y guarda una copia versionada.
    """
    os.makedirs(VERSIONS_DIR, exist_ok=True)

    # 1. Crear backup de la configuración actual antes de modificarla
    backup_path = CONFIG_PATH.replace(".json", f"_backup_{datetime.now().strftime('%Y%m%d')}.json")
    shutil.copy(CONFIG_PATH, backup_path)

    # 2. Cargar configuración, actualizarla y guardarla
    with open(CONFIG_PATH, "r") as f:
        config = json.load(f)
    config.update(new_params)
    with open(CONFIG_PATH, "w") as f:
        json.dump(config, f, indent=4)

    # 3. Guardar la nueva configuración como una versión con timestamp
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    version_path = os.path.join(VERSIONS_DIR, f"config_v1_{timestamp}.json")
    shutil.copy(CONFIG_PATH, version_path)
    print(f"\n✅ Configuración actualizada. Nueva versión guardada en: {version_path}")
    print(f"   (Backup de la versión anterior guardado en: {backup_path})")

def update_history_summary(params: dict, winrate: float, total_trades: int):
    """Añade la configuración y su rendimiento al log histórico."""
    summary = {}
    if os.path.exists(HISTORY_SUMMARY_FILE):
        with open(HISTORY_SUMMARY_FILE, 'r') as f:
            summary = json.load(f)

    timestamp = datetime.now().strftime("%Y-%m-%d_%H:%M:%S")
    summary[timestamp] = {
        **params,
        "session_winrate": round(winrate, 4),
        "total_trades_in_session": total_trades
    }

    with open(HISTORY_SUMMARY_FILE, 'w') as f:
        json.dump(summary, f, indent=4)
    print(f"🧠 Memoria evolutiva actualizada en '{HISTORY_SUMMARY_FILE}'")

def simulate_new_params(df: pd.DataFrame, new_params: dict) -> float:
    """
    Simula el rendimiento de los nuevos parámetros sobre el historial de trades.
    Retorna el winrate proyectado.
    """
    if df.empty:
        return 0.0

    wins = 0
    applicable_trades = 0

    for _, trade in df.iterrows():
        # Simulación de PUT
        if trade['direction'] == 'put':
            if trade['rsi'] > new_params.get('RSI_OVERBOUGHT', 70) and trade['bb_width'] > new_params.get('MIN_BB_WIDTH', 0):
                applicable_trades += 1
                if trade['result'] == 'win':
                    wins += 1
        # Simulación de CALL
        elif trade['direction'] == 'call':
            if trade['rsi'] < new_params.get('RSI_OVERSOLD', 30) and trade['bb_width'] > new_params.get('MIN_BB_WIDTH', 0):
                applicable_trades += 1
                if trade['result'] == 'win':
                    wins += 1

    if applicable_trades == 0:
        return 0.0

    return wins / applicable_trades

def analyze_trades():
    """
    Lee el historial de trades y sugiere nuevos parámetros para la estrategia.
    """
    if not os.path.exists(TRADE_LOG_FILE):
        print(f"❌ No se encontró el archivo de historial '{TRADE_LOG_FILE}'. Ejecuta el bot primero.")
        return

    df = pd.read_csv(TRADE_LOG_FILE)
    df['timestamp'] = pd.to_datetime(df['timestamp']) # Asegurar que es datetime
    df['win'] = (df['result'] == 'win').astype(int)

    if len(df) < 20:
        print(f"📉 No hay suficientes datos ({len(df)} trades). Se necesitan al menos 20 para un análisis significativo.")
        return

    print("📊 ANÁLISIS DE RENDIMIENTO DE LA ESTRATEGIA\n")

    # --- Cargar configuración actual ---
    with open(CONFIG_PATH, 'r') as f:
        current_config = json.load(f)
    print("⚙️ Configuración Actual:")
    print(json.dumps(current_config, indent=2))

    # --- Análisis de RSI ---
    # Para PUTS (sells), buscamos el RSI más bajo que aún gana
    puts = df[df['direction'] == 'put']
    if not puts.empty:
        rsi_put_win_avg = puts[puts['win'] == 1]['rsi'].mean()
        suggested_rsi_overbought = np.floor(rsi_put_win_avg) if not np.isnan(rsi_put_win_avg) else current_config['RSI_OVERBOUGHT']
        print(f"\nAnálisis de PUTs (RSI Overbought):")
        print(f"  - RSI promedio en GANADAS: {rsi_put_win_avg:.2f}")
        print(f"  - Sugerencia para 'RSI_OVERBOUGHT': {suggested_rsi_overbought} (actual: {current_config['RSI_OVERBOUGHT']})")

    # Para CALLS (buys), buscamos el RSI más alto que aún gana
    calls = df[df['direction'] == 'call']
    if not calls.empty:
        rsi_call_win_avg = calls[calls['win'] == 1]['rsi'].mean()
        suggested_rsi_oversold = np.ceil(rsi_call_win_avg) if not np.isnan(rsi_call_win_avg) else current_config['RSI_OVERSOLD']
        print(f"\nAnálisis de CALLs (RSI Oversold):")
        print(f"  - RSI promedio en GANADAS: {rsi_call_win_avg:.2f}")
        print(f"  - Sugerencia para 'RSI_OVERSOLD': {suggested_rsi_oversold} (actual: {current_config['RSI_OVERSOLD']})")

    # --- Análisis de BB_WIDTH ---
    bb_width_win_avg = df[df['win'] == 1]['bb_width'].mean()
    suggested_min_bb_width = round(bb_width_win_avg * 0.8, 5) if not np.isnan(bb_width_win_avg) else current_config['MIN_BB_WIDTH'] # 80% del promedio ganador
    print(f"\nAnálisis de Volatilidad (BB Width):")
    print(f"  - Ancho de banda promedio en GANADAS: {bb_width_win_avg:.5f}")
    print(f"  - Sugerencia para 'MIN_BB_WIDTH': {suggested_min_bb_width} (actual: {current_config['MIN_BB_WIDTH']})")

    # --- D. Meta-aprendizaje sobre horario ---
    df['hour'] = df['timestamp'].dt.hour
    hourly_performance = df.groupby('hour')['win'].agg(['mean', 'count']).rename(columns={'mean': 'winrate'})
    profitable_hours = hourly_performance[
        (hourly_performance['winrate'] > 0.55) & (hourly_performance['count'] >= 5)
    ]

    if not profitable_hours.empty:
        suggested_start = profitable_hours.index.min()
        suggested_end = profitable_hours.index.max() + 1
        print(f"\nAnálisis de Horario:")
        print(f"  - Mejores horas (winrate > 55% y >5 trades): {profitable_hours.index.tolist()}")
        print(f"  - Sugerencia para 'TRADING_START_HOUR': {suggested_start} (actual: {current_config['TRADING_START_HOUR']})")
        print(f"  - Sugerencia para 'TRADING_END_HOUR': {suggested_end} (actual: {current_config['TRADING_END_HOUR']})")
    else:
        suggested_start = current_config['TRADING_START_HOUR']
        suggested_end = current_config['TRADING_END_HOUR']

    # --- Aplicar cambios automáticamente ---
    auto_update = input("\n¿Deseas aplicar automáticamente los nuevos parámetros sugeridos? (y/n): ").lower()
    if auto_update == "y":
        new_params = {
            "RSI_OVERBOUGHT": int(suggested_rsi_overbought),
            "RSI_OVERSOLD": int(suggested_rsi_oversold),
            "MIN_BB_WIDTH": suggested_min_bb_width,
            "TRADING_START_HOUR": int(suggested_start),
            "TRADING_END_HOUR": int(suggested_end)
        }

        # A. Validación para evitar aprendizaje regresivo
        last_50_trades = df.tail(50)
        last_winrate = last_50_trades['win'].mean()
        projected_winrate = simulate_new_params(last_50_trades, new_params)

        print(f"\nValidando mejora: Winrate actual (últimas 50) = {last_winrate:.2%}, Proyectado = {projected_winrate:.2%}")
        if projected_winrate > last_winrate:
            update_config_file(new_params)
            # B. Guardar en memoria evolutiva
            update_history_summary(new_params, projected_winrate, len(df))
        else:
            print("⚠️ No se aplica el cambio: la proyección no muestra una mejora significativa.")
    else:
        print("\n💡 PRÓXIMOS PASOS:")
        print("1. Revisa las sugerencias de arriba.")
        print(f"2. Si parecen lógicas, puedes actualizar manualmente el archivo '{CONFIG_PATH}'.")


if __name__ == "__main__":
    analyze_trades()