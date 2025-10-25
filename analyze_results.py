import os
import re
import sys
from datetime import datetime, timedelta
import pandas as pd
from tabulate import tabulate

# ──────────────────────────────────────────────
# 🔍 Buscar logs recientes
# ──────────────────────────────────────────────
def find_log_files(days_to_check: int):
    log_dir = "logs"
    if not os.path.exists(log_dir):
        print(f"❌ No se encontró la carpeta '{log_dir}'.")
        return []

    log_files = []
    for i in range(days_to_check):
        date = datetime.now() - timedelta(days=i)
        log_filename = f"bot_{date.strftime('%Y-%m-%d')}.log"
        log_path = os.path.join(log_dir, log_filename)
        if os.path.exists(log_path):
            log_files.append(log_path)

    # fallback: si no hay logs recientes, tomar el más nuevo
    if not log_files:
        all_logs = sorted(
            [f for f in os.listdir(log_dir) if f.startswith("bot_") and f.endswith(".log")],
            reverse=True
        )
        if all_logs:
            print(f"⚠️ No se encontraron logs de los últimos {days_to_check} días. Analizando el más reciente: {all_logs[0]}")
            log_files.append(os.path.join(log_dir, all_logs[0]))

    return log_files


# ──────────────────────────────────────────────
# 📈 Analizar logs
# ──────────────────────────────────────────────
def analyze_logs(log_files: list):
    if not log_files:
        print("❌ No se encontraron archivos de log para analizar.")
        return

    print(f"📊 Analizando {len(log_files)} archivo(s) de log...")

    trades = []
    current_signal_info = None

    for log_path in log_files:
        with open(log_path, "r", encoding="utf-8") as f:
            for line in f:
                # Detectar señal
                signal_match = re.search(r"SIGNAL: (BUY|SELL).*reasons=(.*)", line)
                if signal_match:
                    reasons = eval(signal_match.group(2))
                    current_signal_info = {"reasons": tuple(sorted(reasons))}
                    continue

                # Detectar resultado
                win_match = re.search(r"(\d{2}:\d{2}:\d{2}).*Operación GANADA", line)
                loss_match = re.search(r"(\d{2}:\d{2}:\d{2}).*Operación PERDIDA", line)

                if (win_match or loss_match) and current_signal_info:
                    match = win_match or loss_match
                    trade_hour = int(match.group(1).split(':')[0])
                    result = 1 if win_match else 0
                    trades.append({
                        "result": result,
                        "hour": trade_hour,
                        **current_signal_info
                    })
                    current_signal_info = None

    if not trades:
        print("\n🤷 No se encontraron operaciones completas (señal + resultado) en los logs.")
        return

    df = pd.DataFrame(trades)
    total_trades = len(df)
    wins = df["result"].sum()
    losses = total_trades - wins
    win_rate = (wins / total_trades * 100).round(2)

    # ──────────────────────────────────────────────
    # 📊 RESUMEN GENERAL
    # ──────────────────────────────────────────────
    print("\n" + "📈 RESULTADOS GENERALES".center(60, "─"))
    print(f"🧾 Total operaciones: {total_trades}")
    print(f"✅ Ganadas:            \033[92m{wins}\033[0m")
    print(f"❌ Perdidas:           \033[91m{losses}\033[0m")
    print(f"🎯 Tasa de acierto:    {win_rate:.2f}%")
    print("─" * 60)

    # ──────────────────────────────────────────────
    # 🧠 ANÁLISIS POR COMBINACIÓN DE RAZONES
    # ──────────────────────────────────────────────
    print("\n" + "🧠 ANÁLISIS POR COMBINACIÓN DE RAZONES".center(60, "─"))

    combo_summary = (
        df.groupby("reasons")["result"]
        .agg(wins=lambda x: (x == 1).sum(), total="count")
        .reset_index()
    )
    combo_summary["losses"] = combo_summary["total"] - combo_summary["wins"]
    combo_summary["win_rate"] = (combo_summary["wins"] / combo_summary["total"] * 100).round(2)

    # Filtrar combinaciones poco relevantes (<3 operaciones)
    combo_summary = combo_summary[combo_summary["total"] >= 3]
    combo_summary = combo_summary.sort_values(by="win_rate", ascending=False)

    if combo_summary.empty:
        print("⚠️ No hay suficientes combinaciones con más de 3 operaciones.")
    else:
        print(tabulate(combo_summary, headers="keys", tablefmt="psql", showindex=False))

    # ──────────────────────────────────────────────
    # 🕒 ANÁLISIS POR HORA
    # ──────────────────────────────────────────────
    print("\n" + "🕒 ANÁLISIS POR HORA".center(60, "─"))

    hour_summary = (
        df.groupby("hour")["result"]
        .agg(wins=lambda x: (x == 1).sum(), total="count")
        .reset_index()
    )
    hour_summary["win_rate"] = (hour_summary["wins"] / hour_summary["total"] * 100).round(2)
    print(tabulate(hour_summary, headers="keys", tablefmt="psql", showindex=False))
    print("─" * 60)

    return combo_summary, hour_summary


# ──────────────────────────────────────────────
# 🚀 MAIN
# ──────────────────────────────────────────────
if __name__ == "__main__":
    try:
        days = int(sys.argv[1]) if len(sys.argv) > 1 else 2
    except ValueError:
        print("Uso: python analyze_results.py [numero_de_dias]")
        sys.exit(1)

    log_files_to_analyze = find_log_files(days)
    analyze_logs(log_files_to_analyze)
